#!/usr/bin/env python3
"""
Events Radar — LLM-based Universal Scraper (Gemini 2.0 Flash)

Scraper universale per fonti fragili (legaltech_generic nel registry vecchio):
invece di parser CSS euristici, passa l'HTML pulito a Gemini 2.0 Flash e chiede
un JSON strutturato con eventi + eventuali follow_urls da navigare (depth max 2).

Designed per sostituire `scrape_legaltech_source` per le 6 fonti:
Legal Tech Forum, GLTH Milano, LegalTechTalk, Lexpo, AIGA, ANF.

Story 3.10 — guardrail: il contratto con `insert_evento`, `geocode_and_update`,
`update_fonte_status`, `is_valid_event` di scraper.scraper e identico a quello
degli scraper custom esistenti (nessuna modifica a queste funzioni).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

log = logging.getLogger("events_radar_scraper.llm")

# --- Costanti modulo ---
LLM_MODEL = "gemini-2.5-flash"
LLM_CALLS_PER_RUN_MAX = 50
LLM_CALL_TIMEOUT = 60
LLM_MAX_RETRIES_429 = 3
LLM_HTML_MAX_CHARS = 30000
LLM_MAX_FOLLOW_URLS = 10
LLM_MAX_DEPTH = 2
LLM_TEMPERATURE = 0.1
LLM_MAX_EVENTS_PER_FONTE = 100  # safety cap
# Budget = WORKER_TIMEOUT_SECONDS(120) − LLM_CALL_TIMEOUT(60) − fetch/processing margin(20) = 40s.
# Rispetta G6 anche nel caso peggiore: se depth-1 supera 40s, niente depth-2 → worker
# finisce entro 120s = 40 + 60(LLM) + 20(fetch+DB) (story 3.10 review fix H1).
LLM_TIME_BUDGET_PER_FONTE = 40

# --- Prompt template ---
PROMPT_TEMPLATE = """Sei un estrattore di eventi legali da siti web.

Fonte: {nome}
URL: {url}

Estrai tutti gli eventi (convegni, corsi, conferenze, fiere, webinar) futuri o recenti
da questo contenuto HTML pulito. Non inventare dati — se un campo non e chiaro, metti null.

Ritorna SOLO JSON valido con questo schema esatto:
{{
  "events": [
    {{
      "titolo": "string obbligatorio",
      "data_inizio": "YYYY-MM-DD o null",
      "luogo": "citta o 'online' o null",
      "url_evento": "URL dettaglio evento o null",
      "descrizione": "breve descrizione o null"
    }}
  ],
  "follow_urls": ["URL della stessa origine con dettagli eventi, max 10"]
}}

HTML pulito:
---
{html_content}
---
"""

# --- Contatore chiamate thread-safe (worker paralleli) ---
_llm_call_counter = 0
_counter_lock = threading.Lock()


def reset_counter() -> None:
    """Reset globale del contatore. Chiamato all'inizio di run_scraper()."""
    global _llm_call_counter
    with _counter_lock:
        _llm_call_counter = 0


def _check_and_increment_counter() -> bool:
    """Ritorna False se il cap e raggiunto, altrimenti incrementa e ritorna True."""
    global _llm_call_counter
    with _counter_lock:
        if _llm_call_counter >= LLM_CALLS_PER_RUN_MAX:
            return False
        _llm_call_counter += 1
        return True


def _decrement_counter() -> None:
    """Rollback del contatore per chiamate che non hanno consumato budget API
    (es. errore di config/parsing locale). 429 e timeout NON vengono rollbackati
    perche rappresentano comunque consumo reale di quota."""
    global _llm_call_counter
    with _counter_lock:
        if _llm_call_counter > 0:
            _llm_call_counter -= 1


def get_counter() -> int:
    with _counter_lock:
        return _llm_call_counter


# --- Normalizzazione titolo per dedup intra-run ---
def _normalize_title_local(title: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (title or "").lower().strip())


# --- HTML cleaning ---
def _clean_html_for_llm(soup) -> str:
    """Ripulisce il DOM: rimuove script/style/nav/footer/header e commenti,
    estrae testo + link inline come "[testo](url)", tronca a LLM_HTML_MAX_CHARS.
    """
    try:
        from bs4 import Comment  # type: ignore
    except Exception:
        Comment = None  # type: ignore

    # Rimuovi tag rumorosi
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()

    # Rimuovi commenti HTML
    if Comment is not None:
        for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
            c.extract()

    # Inline dei link come "[testo](url)" sostituendo il contenuto dell'<a>
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        href = a["href"]
        if txt:
            a.replace_with(f"[{txt}]({href})")
        else:
            a.decompose()

    body = soup.body or soup
    text = body.get_text(separator="\n", strip=True)
    # Collassa linee vuote multiple
    text = re.sub(r"\n{3,}", "\n\n", text)

    if len(text) > LLM_HTML_MAX_CHARS:
        text = text[:LLM_HTML_MAX_CHARS]
    return text


# --- Gemini call ---
def _call_gemini(prompt: str) -> dict:
    """Invoca Gemini 2.0 Flash con JSON response_mime_type e temperature bassa.

    Retry su 429 con backoff esponenziale 1s/2s/4s (max LLM_MAX_RETRIES_429).
    Raise ValueError se JSON malformato o schema invalido.
    Raise altre eccezioni per gestione nel chiamante.
    """
    import google.generativeai as genai  # lazy import
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

    model = genai.GenerativeModel(LLM_MODEL)

    def _invoke():
        return model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": LLM_TEMPERATURE,
            },
            request_options={"timeout": LLM_CALL_TIMEOUT},
        )

    last_exc: Optional[Exception] = None
    for attempt in range(LLM_MAX_RETRIES_429 + 1):
        try:
            # Defense-in-depth: hard timeout a livello applicativo per blindare G6
            # nel caso request_options non venga onorato dal SDK (story 3.10 review fix M1).
            with ThreadPoolExecutor(max_workers=1) as _ex:
                _future = _ex.submit(_invoke)
                try:
                    response = _future.result(timeout=LLM_CALL_TIMEOUT + 5)
                except FuturesTimeoutError:
                    _future.cancel()
                    raise TimeoutError(f"Gemini call exceeded {LLM_CALL_TIMEOUT + 5}s hard timeout")
            raw = (getattr(response, "text", None) or "").strip()
            if not raw:
                raise ValueError("LLM returned empty response")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"LLM returned malformed JSON: {e}")

            # Schema validation
            if not isinstance(data, dict):
                raise ValueError("LLM response is not a JSON object")
            events = data.get("events")
            if events is None:
                events = []
            if not isinstance(events, list):
                raise ValueError("LLM 'events' is not a list")
            follow_urls = data.get("follow_urls") or []
            if not isinstance(follow_urls, list):
                follow_urls = []
            # Filter events missing titolo
            valid_events = []
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                titolo = ev.get("titolo")
                if not isinstance(titolo, str) or not titolo.strip():
                    continue
                valid_events.append(ev)
            return {"events": valid_events, "follow_urls": follow_urls}
        except Exception as e:
            # Detect 429 / ResourceExhausted for backoff
            name = type(e).__name__
            is_429 = (
                name == "ResourceExhausted"
                or "429" in str(e)
                or "quota" in str(e).lower()
                or "rate" in str(e).lower()
            )
            if is_429 and attempt < LLM_MAX_RETRIES_429:
                wait = 2 ** attempt  # 1, 2, 4
                log.warning(f"Gemini 429 rate limit, backoff {wait}s (attempt {attempt+1}/{LLM_MAX_RETRIES_429})")
                time.sleep(wait)
                last_exc = e
                continue
            raise
    # Should not reach
    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini call failed without explicit exception")


# --- HTML extraction (riusa fetch_html di scraper.scraper) ---
def _fetch_and_clean(url: str) -> Optional[str]:
    from scraper.scraper import fetch_html  # lazy import circolare
    soup = fetch_html(url)
    if soup is None:
        return None
    return _clean_html_for_llm(soup)


def _extract_events_from_html(html_content: str, nome: str, url: str) -> dict:
    """Invoca Gemini sul contenuto HTML pulito. Ritorna {events, follow_urls}.

    Incrementa il counter PRIMA della chiamata; ritorna dict vuoto se cap raggiunto.
    """
    if not _check_and_increment_counter():
        log.error(f"LLM call cap reached ({LLM_CALLS_PER_RUN_MAX}), skipping {nome}")
        return {"events": [], "follow_urls": [], "_cap_reached": True}
    prompt = PROMPT_TEMPLATE.format(nome=nome, url=url, html_content=html_content)
    try:
        return _call_gemini(prompt)
    except Exception as e:
        # Rollback counter per errori che non rappresentano consumo reale della quota
        # API (config errata / JSON malformato / schema invalido). Timeout e 429
        # restano conteggiati (rappresentano chiamate realmente effettuate).
        name = type(e).__name__
        is_quota = (
            name == "ResourceExhausted"
            or "429" in str(e)
            or "quota" in str(e).lower()
            or isinstance(e, TimeoutError)
        )
        if not is_quota:
            _decrement_counter()
        raise


# --- Date parsing helper (delegates a parse_date_from_text di scraper.scraper se formato libero) ---
_DATE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_llm_date(value: Optional[str]) -> Optional[str]:
    """Accetta solo formato YYYY-MM-DD dal LLM; altrimenti prova parse libero via scraper.parse_date_from_text."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if _DATE_ISO_RE.match(value):
        # Verifica validita base: anno ragionevole, mese/giorno validi
        try:
            from datetime import datetime as _dt
            _dt.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            return None
    # Fallback: il modello potrebbe aver ignorato le istruzioni — prova parse libero
    try:
        from scraper.scraper import parse_date_from_text
        parsed = parse_date_from_text(value)
        log.warning(f"LLM returned non-ISO date {value!r}; fallback parse → {parsed!r}")
        return parsed
    except Exception:
        log.warning(f"LLM returned unparseable date {value!r}; dropping")
        return None


# --- Luogo normalization ---
def _normalize_luogo_llm(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    return v[:255]


# --- Follow URLs filter ---
def _filter_follow_urls(candidates: list, base_url: str) -> list:
    base_netloc = urlparse(base_url).netloc.lower()
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if not isinstance(c, str) or not c.strip():
            continue
        # Absolute-ify URL relativo
        absu = urljoin(base_url, c.strip())
        parsed = urlparse(absu)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != base_netloc:
            continue
        if absu == base_url:
            continue
        if absu in seen:
            continue
        seen.add(absu)
        out.append(absu)
        if len(out) >= LLM_MAX_FOLLOW_URLS:
            break
    return out


# --- Main entry point ---
def scrape_with_llm(
    conn,
    fonte_id: int,
    nome: str,
    url: str,
    mercato: str = "italia",
    dry_run: bool = False,
) -> tuple[int, int, bool]:
    """Scraper LLM-based universale.

    Fetch listing → clean → Gemini → opzionalmente segue follow_urls (depth 2) →
    insert_evento per ogni evento valido.

    Return: (inserted, updated, had_error).

    Comportamento dry-run: NON scrive DB, NON fa geocoding, NON chiama
    update_fonte_status. Logga ogni evento con "[DRY-RUN]".
    """
    from scraper.scraper import (
        insert_evento,
        geocode_and_update,
        update_fonte_status,
        is_valid_event,
        _ONLINE_KEYWORDS,
    )

    # Guardia API key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log.error(f"GEMINI_API_KEY not set, skipping LLM scraper for {nome}")
        if not dry_run:
            try:
                update_fonte_status(conn, fonte_id, False)
            except Exception:
                pass
        return 0, 0, True

    # Configura genai (idempotente tra chiamate)
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
    except ImportError:
        log.error(f"google-generativeai not installed, skipping LLM scraper for {nome}")
        if not dry_run:
            try:
                update_fonte_status(conn, fonte_id, False)
            except Exception:
                pass
        return 0, 0, True
    except Exception as e:
        log.error(f"genai.configure failed for {nome}: {e}")
        if not dry_run:
            try:
                update_fonte_status(conn, fonte_id, False)
            except Exception:
                pass
        return 0, 0, True

    log.info(f"Scraping {nome} via LLM ({url})...")
    start_time = time.monotonic()

    # --- Depth 1: listing ---
    all_events: list[dict] = []
    follow_urls: list[str] = []

    try:
        html_content = _fetch_and_clean(url)
        if html_content is None:
            log.warning(f"{nome}: fetch/clean failed for listing")
            if not dry_run:
                try:
                    update_fonte_status(conn, fonte_id, False)
                except Exception:
                    pass
            return 0, 0, True

        result = _extract_events_from_html(html_content, nome, url)
        if result.get("_cap_reached"):
            if not dry_run:
                try:
                    update_fonte_status(conn, fonte_id, False)
                except Exception:
                    pass
            return 0, 0, True
        all_events.extend(result.get("events", []))
        follow_urls = _filter_follow_urls(result.get("follow_urls", []), url)
    except Exception as e:
        log.error(f"{nome}: LLM call failed on listing: {type(e).__name__}: {e}")
        if not dry_run:
            try:
                update_fonte_status(conn, fonte_id, False)
            except Exception:
                pass
        return 0, 0, True

    # --- Depth 2: follow URLs (bounded by time budget G6) ---
    for furl in follow_urls:
        elapsed = time.monotonic() - start_time
        if elapsed >= LLM_TIME_BUDGET_PER_FONTE:
            log.warning(f"{nome}: time budget ({LLM_TIME_BUDGET_PER_FONTE}s) exhausted at depth=2, stopping follow_urls")
            break
        try:
            html2 = _fetch_and_clean(furl)
            if html2 is None:
                continue
            r2 = _extract_events_from_html(html2, nome, furl)
            if r2.get("_cap_reached"):
                log.warning(f"{nome}: LLM cap reached during follow_urls — partial results")
                break
            all_events.extend(r2.get("events", []))
        except Exception as e:
            log.warning(f"{nome}: follow_url {furl} failed: {type(e).__name__}: {e}")
            continue

    log.info(f"  {nome}: extracted {len(all_events)} raw events (LLM calls so far: {get_counter()})")

    # --- Dedup intra-run e persistenza ---
    seen: set[tuple[str, Optional[str]]] = set()
    inserted = 0
    updated = 0
    dry_run_count = 0
    paese_geo = "internazionale" if mercato == "internazionale" else "Italia"
    # tipo coerente con scrape_legaltech_source
    tipo = (
        "fiera_legaltech"
        if "legaltech" in nome.lower() or "legal tech" in nome.lower()
        else "convegno"
    )

    processed = 0
    for ev in all_events:
        if processed >= LLM_MAX_EVENTS_PER_FONTE:
            log.warning(f"{nome}: hit per-fonte event cap ({LLM_MAX_EVENTS_PER_FONTE})")
            break
        processed += 1
        try:
            titolo_raw = ev.get("titolo") or ""
            titolo = titolo_raw.strip()[:500]
            data_inizio = _parse_llm_date(ev.get("data_inizio"))
            luogo_text = _normalize_luogo_llm(ev.get("luogo"))
            url_evento = ev.get("url_evento")
            if url_evento and isinstance(url_evento, str):
                # absolute-ify
                try:
                    url_evento = urljoin(url, url_evento.strip())
                except Exception:
                    url_evento = None
            else:
                url_evento = None

            # Validation (is_valid_event guardrail)
            if not is_valid_event(titolo, data_inizio):
                log.debug(f"  {nome}: noise skip: {titolo[:60]!r}")
                continue

            # Dedup intra-run
            key = (_normalize_title_local(titolo), data_inizio)
            if key in seen:
                continue
            seen.add(key)

            evento = {
                "titolo": titolo,
                "data_inizio": data_inizio,
                "luogo": luogo_text,
                "tipo_evento": tipo,
                "organizzatore": nome,
                "url_sorgente": url_evento or url,
                "mercato": mercato,
            }

            if dry_run:
                log.info(f"[DRY-RUN] {nome}: {json.dumps(evento, ensure_ascii=False)}")
                dry_run_count += 1
                continue

            result_id = insert_evento(conn, evento, fonte_id)
            if result_id is not None and result_id > 0:
                # Evento nuovo
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    try:
                        geocode_and_update(conn, result_id, luogo_text, paese_geo)
                    except Exception as e:
                        log.warning(f"{nome}: geocode failed for {luogo_text!r}: {e}")
                inserted += 1
            elif result_id is not None and result_id < 0:
                # Update con luogo cambiato
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    try:
                        geocode_and_update(conn, abs(result_id), luogo_text, paese_geo)
                    except Exception as e:
                        log.warning(f"{nome}: geocode failed for {luogo_text!r}: {e}")
                updated += 1
            elif result_id == 0:
                updated += 1
        except Exception as e:
            log.warning(f"{nome}: error processing event: {type(e).__name__}: {e}")
            continue

    if dry_run:
        log.info(f"{nome}: [DRY-RUN] {dry_run_count} events extracted, 0 DB writes")
        return dry_run_count, 0, False

    log.info(f"{nome}: {inserted} new, {updated} updated (LLM)")
    try:
        update_fonte_status(conn, fonte_id, True)
    except Exception as e:
        log.warning(f"{nome}: update_fonte_status failed: {e}")
    return inserted, updated, False
