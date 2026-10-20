#!/usr/bin/env python3
"""
Events Radar — Web Scraper
Collects Italian and international legal events from public sources.
"""

import hashlib
import os
import re
import sys
import time
import logging
import threading
import psycopg2
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, date, timedelta
from typing import Optional
from urllib.parse import urlparse

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("events_radar_scraper")

# --- DB connection ---
# DATABASE_URL is only required when a DB connection is actually opened
# (scraper runs, not at import-time), so that unit tests can import helpers
# like parse_date_from_text / is_valid_event without a live DB config.
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_conn():
    if not DATABASE_URL:
        log.error("DATABASE_URL not set. Exiting.")
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL)

# --- Helpers ---
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EventsRadarBot/1.0; "
        "+https://github.com/Luke2986/events-radar)"
    )
}

def sleep():
    """Rate limit: 1 req/s per source — prevents IP ban."""
    time.sleep(1.0)


def sleep_geocode():
    """Rate limit for Nominatim: strictly >= 1s between requests per ToS."""
    time.sleep(1.0)


def fetch_html(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    """Fetch URL and return BeautifulSoup, or None on error.

    Uses resp.content (raw bytes) so BeautifulSoup/lxml can detect the real
    charset from the HTML <meta charset> tag rather than trusting the HTTP
    Content-Type header, which sites often set incorrectly (e.g. iso-8859-1
    when the body is actually UTF-8).
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "lxml")
    except Exception as e:
        log.warning(f"Fetch failed for {url}: {e}")
        return None


# In-memory geocode cache: normalized city string → (lat, lng).
# A single lock both protects the dict AND serializes Nominatim calls
# so we never exceed 1 req/sec even under parallel scraping.
_geocode_cache: dict[tuple[str, str], tuple[Optional[float], Optional[float]]] = {}
_geocode_lock = threading.Lock()


def prewarm_geocode_cache(conn) -> None:
    """Load known city→coords from existing DB rows into the module-level cache."""
    with conn.cursor() as cur:
        # 1. Carica geocoding riusciti
        cur.execute(
            "SELECT DISTINCT luogo, lat, lng, mercato FROM evento "
            "WHERE lat IS NOT NULL AND lng IS NOT NULL AND luogo IS NOT NULL"
        )
        success_rows = cur.fetchall()

        # 2. Carica geocoding falliti recenti (< 7 giorni) per evitare ritentarli
        cur.execute(
            "SELECT DISTINCT luogo, mercato FROM evento "
            "WHERE luogo IS NOT NULL AND luogo != 'online' "
            "AND lat IS NULL AND lng IS NULL "
            "AND geocoding_attempted_at IS NOT NULL "
            "AND geocoding_attempted_at > NOW() - INTERVAL '7 days'"
        )
        failed_rows = cur.fetchall()

    loaded = 0
    loaded_failed = 0
    with _geocode_lock:
        for luogo, lat, lng, mercato in success_rows:
            paese = "internazionale" if mercato == "internazionale" else "italia"
            key = (luogo.lower().strip(), paese)
            if key not in _geocode_cache:
                _geocode_cache[key] = (float(lat), float(lng))
                loaded += 1

        for luogo, mercato in failed_rows:
            paese = "internazionale" if mercato == "internazionale" else "italia"
            key = (luogo.lower().strip(), paese)
            if key not in _geocode_cache:
                _geocode_cache[key] = (None, None)
                loaded_failed += 1

    log.info(f"Geocode cache pre-warmed: {loaded} success + {loaded_failed} failed locations.")


def geocode_luogo(luogo: str, paese: str = "Italia") -> tuple[Optional[float], Optional[float]]:
    """Geocode a location string using Nominatim (OpenStreetMap).

    Results are cached in _geocode_cache.  The single _geocode_lock
    serialises all Nominatim calls across threads (rate-limit guarantee).
    """
    if not luogo or luogo.lower() == "online":
        return None, None
    # Cache key includes paese to avoid collisions (e.g. "Bologna" Italia vs "Bologna" USA)
    key = (luogo.lower().strip(), paese.lower().strip())

    with _geocode_lock:
        if key in _geocode_cache:
            cached = _geocode_cache[key]
            if cached == (None, None):
                log.debug(f"Geocode cache hit (failed): '{luogo}'")
            else:
                log.debug(f"Geocode cache hit: '{luogo}' -> ({cached[0]}, {cached[1]})")
            return cached

        sleep_geocode()
        result: tuple[Optional[float], Optional[float]] = (None, None)
        try:
            url = "https://nominatim.openstreetmap.org/search"
            # Per fonti internazionali, non appendere paese
            q = luogo if paese.lower() == "internazionale" else f"{luogo}, {paese}"
            params = {"q": q, "format": "json", "limit": 1}
            resp = requests.get(
                url,
                params=params,
                headers={"User-Agent": "EventsRadar/1.0 (+https://github.com/Luke2986/events-radar)"},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                result = (float(data[0]["lat"]), float(data[0]["lon"]))
        except Exception as e:
            log.warning(f"Geocoding failed for '{luogo}': {e}")

        _geocode_cache[key] = result  # Cache SEMPRE, anche (None, None)
        return result

def get_fonte_id(conn, nome: str) -> Optional[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM fonte WHERE nome = %s", (nome,))
        row = cur.fetchone()
        return row[0] if row else None

def get_active_fonti(conn) -> list[tuple[int, str]]:
    """Return list of (id, nome) for all fonti with stato_scraper = 'attivo'."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, nome FROM fonte WHERE stato_scraper = 'attivo' ORDER BY id")
        return cur.fetchall()

def update_fonte_status(conn, fonte_id: int, success: bool):
    with conn.cursor() as cur:
        if success:
            cur.execute(
                """
                UPDATE fonte SET stato_scraper='attivo', ultimo_scrape=NOW(), fallimenti_consecutivi=0
                WHERE id = %s
                """,
                (fonte_id,)
            )
        else:
            cur.execute(
                """
                UPDATE fonte
                SET fallimenti_consecutivi = fallimenti_consecutivi + 1,
                    stato_scraper = CASE WHEN fallimenti_consecutivi + 1 >= 3 THEN 'errore' ELSE stato_scraper END
                WHERE id = %s
                """,
                (fonte_id,)
            )
    conn.commit()

def _normalize_title(title: Optional[str]) -> str:
    """Normalize title for dedup: lowercase, strip, collapse whitespace."""
    return re.sub(r"\s+", " ", (title or "").lower().strip())


def _make_source_event_uid(titolo: str, data_inizio: Optional[str], id_fonte: int) -> str:
    """Deterministic dedup UID — sha256(titolo_norm|data_inizio|id_fonte)[:32].

    Stesso algoritmo usato in backfill SQL e scraper/backfill_source_event_uid.py.
    Single source of truth per la deduplica (story 3.7).
    """
    norm_title = _normalize_title(titolo or "")
    date_str = data_inizio or ""
    payload = f"{norm_title}|{date_str}|{id_fonte or 0}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────────────
# Date extraction utilities
# ─────────────────────────────────────────────────────────────────────────────

MESI_IT: dict[str, int] = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
    # English fallback for international sources
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "dec": 12,
}

_MESI_PATTERN = "|".join(sorted(MESI_IT.keys(), key=len, reverse=True))
RE_DATE_SLASHDASH = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b")
RE_DATE_ITALIAN = re.compile(
    r"\b(\d{1,2})\s+(" + _MESI_PATTERN + r")\s+(\d{4})\b", re.IGNORECASE
)
RE_DATE_ITALIAN_NOYEAR = re.compile(
    # Negative lookahead: skip matches where a 4-digit year immediately follows
    # (those are handled by RE_DATE_ITALIAN above, which enforces the 2024 cutoff).
    # Without this, "15 giugno 2023" would bypass the cutoff by falling through
    # to the noyear branch and being reinterpreted as the current/next year.
    r"\b(\d{1,2})\s+(" + _MESI_PATTERN + r")\b(?!\s+\d{4})", re.IGNORECASE
)
RE_DATE_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
RE_DATE_DATETIME_ATTR = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def parse_date_from_text(text: str) -> Optional[str]:
    """Try to extract the first plausible future-or-recent date from arbitrary text.

    Returns an ISO date string (YYYY-MM-DD) or None.
    Rejects dates before 2024 to avoid capturing old archived content.
    """
    if not text:
        return None
    today = date.today()
    cutoff = date(2024, 1, 1)

    def _valid_ymd(y: int, mo: int, d: int) -> Optional[str]:
        try:
            candidate = date(y, mo, d)
            if candidate >= cutoff:
                return f"{y:04d}-{mo:02d}-{d:02d}"
        except ValueError:
            pass
        return None

    for m in RE_DATE_ISO.finditer(text):
        result = _valid_ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if result:
            return result

    for m in RE_DATE_ITALIAN.finditer(text):
        mo_num = MESI_IT.get(m.group(2).lower())
        if mo_num:
            result = _valid_ymd(int(m.group(3)), mo_num, int(m.group(1)))
            if result:
                return result

    for m in RE_DATE_SLASHDASH.finditer(text):
        d_num, mo_num, y_num = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo_num <= 12 and 1 <= d_num <= 31:
            result = _valid_ymd(y_num, mo_num, d_num)
            if result:
                return result

    for m in RE_DATE_ITALIAN_NOYEAR.finditer(text):
        mo_num = MESI_IT.get(m.group(2).lower())
        if mo_num:
            d_num = int(m.group(1))
            if 1 <= d_num <= 31:
                y = today.year
                try:
                    candidate = date(y, mo_num, d_num)
                    if candidate < today:
                        y += 1
                    result = _valid_ymd(y, mo_num, d_num)
                    if result:
                        return result
                except ValueError:
                    pass

    return None


_DATE_CLASS_KEYWORDS = ["date", "data", "when", "time", "calendario", "evento-data", "event-date"]


def _search_date_in_node(node) -> Optional[str]:
    """Check a single BS4 node (and its descendants) for a parseable date."""
    if not hasattr(node, "get_text"):
        return None
    if hasattr(node, "get") and node.get("datetime", ""):
        m = RE_DATE_DATETIME_ATTR.search(node["datetime"])
        if m:
            result = parse_date_from_text(m.group(0))
            if result:
                return result
    cls = " ".join(node.get("class", [])) if hasattr(node, "get") else ""
    if any(kw in cls.lower() for kw in _DATE_CLASS_KEYWORDS):
        result = parse_date_from_text(node.get_text(strip=True))
        if result:
            return result
    return parse_date_from_text(node.get_text(" ", strip=True))


def extract_date_from_element(element) -> Optional[str]:
    """Search an element for a date using multiple strategies.

    1. <time datetime="..."> attribute within element
    2. Descendant elements with date-related CSS classes
    3. Regex over the element's full text content
    4. If element is a bare heading (h2/h3/h4), also traverse parent container
       and its direct children to find adjacent date metadata.
    """
    if not hasattr(element, "find_all"):
        return None

    for t in element.find_all("time"):
        dt = t.get("datetime", "")
        if dt:
            m = RE_DATE_DATETIME_ATTR.search(dt)
            if m:
                result = parse_date_from_text(m.group(0))
                if result:
                    return result
        result = parse_date_from_text(t.get_text(strip=True))
        if result:
            return result

    for el in element.find_all(["span", "div", "p", "small", "em"]):
        cls = " ".join(el.get("class", []))
        if any(kw in cls.lower() for kw in _DATE_CLASS_KEYWORDS):
            result = parse_date_from_text(el.get_text(strip=True))
            if result:
                return result

    result = parse_date_from_text(element.get_text(" ", strip=True))
    if result:
        return result

    tag_name = getattr(element, "name", None)
    if tag_name in ("h1", "h2", "h3", "h4"):
        parent = element.parent
        if parent and hasattr(parent, "find_all"):
            for sibling in parent.find_all(
                ["span", "div", "p", "time", "small", "em"], recursive=False
            ):
                result = _search_date_in_node(sibling)
                if result:
                    return result
            result = parse_date_from_text(parent.get_text(" ", strip=True))
            if result:
                return result

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Location extraction
# ─────────────────────────────────────────────────────────────────────────────

_LOCATION_CLASS_KEYWORDS = [
    "location", "luogo", "sede", "indirizzo", "venue", "citta", "city", "where", "dove",
]

_ONLINE_KEYWORDS = {"online", "webinar", "streaming", "da remoto", "in remoto", "virtuale", "fad", "piattaforma", "a distanza", "e-learning"}


def _is_likely_online(titolo: Optional[str], tipo_evento: Optional[str], luogo: Optional[str]) -> bool:
    """True se titolo/tipo suggeriscono evento online, anche se il luogo
    estratto punta all'indirizzo dell'organizzatore (caso frequente quando
    lo scraper usa l'header della pagina come fallback)."""
    if luogo and luogo.lower().strip() == "online":
        return True
    if tipo_evento == "webinar":
        return True
    if titolo:
        t = titolo.lower()
        if any(kw in t for kw in _ONLINE_KEYWORDS):
            return True
    return False

_LEGALTECH_DEFAULT_LOCATION: dict[str, Optional[str]] = {
    "Legal Tech Forum": "Bologna",
    "GLTH Milano": "Milano",
    "AIGA": None,             # associazione nazionale, eventi in tutta Italia — nessun default sicuro
    "ANF": None,              # associazione nazionale, eventi in tutta Italia — nessun default sicuro
    "LegalTechTalk": None,    # internazionale, nessun default
    "Lexpo": "Amsterdam",
}


def _extract_luogo_from_element(item) -> Optional[str]:
    """Extract location from an event element.

    Strategy (cascading fallback):
    1. Tags/classes with location-related keywords
    2. <address> or itemprop="location" tags
    3. If item is a heading, search parent container for <span> elements
       that look like location text (not a date, not a link label)
    4. Regex pattern "Luogo: ...", "Sede: ..." in full text
    5. Return None if nothing found
    """
    if not hasattr(item, "find"):
        return None

    # 1. Look for elements with location-related CSS classes
    for kw in _LOCATION_CLASS_KEYWORDS:
        tag = item.find(class_=lambda c: c and kw in c.lower())
        if tag:
            text = tag.get_text(strip=True)
            if text and len(text) > 2:
                return _normalize_luogo(text)

    # 2. <address> or itemprop="location"
    addr = item.find("address") or item.find(attrs={"itemprop": "location"})
    if addr:
        text = addr.get_text(strip=True)
        if text:
            return _normalize_luogo(text)

    # 3. Resolve container (navigate to parent if item is a heading)
    tag_name = getattr(item, "name", None)
    container = item
    if tag_name in ("h1", "h2", "h3", "h4"):
        container = item.parent

    # 4. Regex pattern "Luogo: ...", "Sede: ..." in full text (before positional scan)
    full_text = ""
    if container and hasattr(container, "get_text"):
        full_text = container.get_text()
    elif hasattr(item, "get_text"):
        full_text = item.get_text()
    match = re.search(
        r'(?:luogo|sede|dove|indirizzo|location|venue)\s*[:\-]\s*(.+?)(?:\n|$)',
        full_text,
        re.IGNORECASE,
    )
    if match:
        text = match.group(1).strip()
        if text and len(text) > 2:
            return _normalize_luogo(text)

    # 5. Positional scan: look for sibling elements that look like location text
    if container and hasattr(container, "find_all"):
        for el in container.find_all(["span", "p", "small", "em"], recursive=False):
            text = el.get_text(strip=True)
            if _looks_like_location(text):
                return _normalize_luogo(text)
        # Also check elements with location-keyword CSS classes
        for el in container.find_all(["span", "p", "div", "small", "em"], recursive=True):
            cls = " ".join(el.get("class", [])) if el.get("class") else ""
            if any(kw in cls.lower() for kw in _LOCATION_CLASS_KEYWORDS):
                text = el.get_text(strip=True)
                if text and len(text) > 2:
                    return _normalize_luogo(text)

    return None


def _normalize_luogo(text: str) -> Optional[str]:
    """Normalize extracted location text. Returns 'online' for virtual events, None for junk."""
    text = text.strip()
    if not text or len(text) < 2:
        return None
    if any(kw in text.lower() for kw in _ONLINE_KEYWORDS):
        return "online"
    # Filter out obvious non-location text (links, button labels, dates-only)
    if text.lower().startswith(("guarda", "scopri", "iscriviti", "leggi", "clicca")):
        return None
    if len(text) > 200:
        return None
    return text


_MESI_IT = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)

_ADDR_KEYWORDS = (
    "via ", "piazza ", "corso ", "viale ", "largo ", "piazzale ",
    "sala ", "palazzo ", "centro ", "hotel ", "sede ",
    "fad", "piattaforma", "remoto", "online", "webinar", "streaming",
)

_DESCRIPTION_STARTS = (
    "dalla", "della", "delle", "degli", "dello", "sulle", "sulla",
    "sugli", "sullo", "nelle", "nella", "negli", "nello",
    "per ", "con ", "tra ", "fra ",
    "il convegno", "la mostra", "il corso", "l'evento", "la conferenza",
    "un ", "una ",
)


def _looks_like_location(text: str) -> bool:
    """Heuristic: does this text look like a location rather than a date, description, or label?"""
    if not text or len(text) < 2 or len(text) > 200:
        return False
    t = text.lower().strip()
    # Skip obvious non-location text
    if t.startswith(("guarda", "scopri", "iscriviti", "leggi", "clicca", "http")):
        return False
    # Skip if it looks like a pure date (all digits, slashes, dashes)
    if re.match(r'^[\d\s/\-\.]+$', t):
        return False
    # Skip very short numbers-only
    if re.match(r'^\d{1,4}$', t):
        return False
    # Skip text that starts with a date pattern (e.g. "15 aprile ore 14:30", "il 27 marzo 2026")
    if re.match(r'^(?:il\s+)?\d{1,2}\s+\w+\s+(?:\d{4}|ore\b)', t):
        return False
    # Skip text containing Italian month names (likely a date or date range)
    if any(m in t for m in _MESI_IT):
        # Allow through if it also has address keywords (e.g. "Via Roma, 15 marzo")
        if not any(kw in t for kw in _ADDR_KEYWORDS):
            return False
    # Skip text starting with "dal/fino/entro" (date ranges)
    if re.match(r'^(?:dal\b|fino\b|entro\b)', t):
        return False
    # Skip text starting with Italian description patterns (articles + prepositions)
    if any(t.startswith(prefix) for prefix in _DESCRIPTION_STARTS):
        return False
    # Positive signals: address-like patterns
    if any(kw in t for kw in _ADDR_KEYWORDS):
        # Exception: "corso di [formazione/aggiornamento/...]" is a training course, not a street
        if re.match(r'corso\s+di\s+', t):
            return False
        return True
    # If it's very short text (max 4 words, < 50 chars) that survived all filters,
    # it might be a city/region name — accept cautiously
    words = t.split()
    if len(words) <= 4 and len(t) < 50:
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Noise / quality filter
# ─────────────────────────────────────────────────────────────────────────────

_NOISE_STARTS = [
    "scopri", "iscriviti", "newsletter", "leggi", "clicca", "torna",
    "vai al", "vai a", "home", "menu", "contatti", "privacy",
    "cookie", "accedi", "login", "register", "subscribe",
    "read more", "learn more", "click here", "more info",
    "dettagli", "back to top", "all events", "tutti gli eventi",
    "archivio", "archive", "tags", "condividi", "share",
]
_NOISE_EXACT = {
    "altri eventi", "prossimi eventi", "eventi passati", "news", "blog",
    "programma", "agenda", "eventi", "formazione", "calendario",
}
RE_NOISE_START = re.compile(
    r"^(" + "|".join(re.escape(w) for w in _NOISE_STARTS) + r")\b",
    re.IGNORECASE,
)
RE_REGION_CITY_NAV = re.compile(
    r"^[\w\sÀ-ÿ]+\s+[–—-]\s+[\w\sÀ-ÿ]+$"
)

EVENT_KEYWORDS = re.compile(
    r"\b(convegno|corso|workshop|webinar|seminario|forum|summit|conferenza"
    r"|fiera|congresso|panel|tavola\s+rotonda|incontro|master|giornata\s+di\s+studio"
    r"|simposio|hackathon|evento|training|bootcamp|lecture)\b",
    re.IGNORECASE,
)

RE_ONLY_NUMS_SYMBOLS = re.compile(
    r'^[\d\s\-–—.,;:!?@#$%^&*()\[\]{}|/\\<>+=~`"\']+$'
)


def is_valid_event(titolo: str, data_inizio: Optional[str] = None) -> bool:
    """Return True if the title looks like a real event, not nav/UI noise.

    Args:
        titolo: Event title to evaluate.
        data_inizio: ISO date string if already known; informational only in
            current implementation (caller enforces date requirements per source).
    """
    t = titolo.strip()

    if len(t) < 15:
        return False

    if RE_ONLY_NUMS_SYMBOLS.match(t):
        return False

    t_lower = t.lower()
    if t_lower in _NOISE_EXACT:
        return False

    if RE_NOISE_START.match(t):
        return False

    if len(t) < 50 and RE_REGION_CITY_NAV.match(t):
        words = re.split(r"[–—-]", t)
        if len(words) == 2 and all(len(w.strip()) < 30 for w in words):
            return False

    return True


def is_noise_title_sql_safe(titolo: str) -> bool:
    """Same logic as is_valid_event but returns True when title IS noise (inverse)."""
    return not is_valid_event(titolo)


# ─────────────────────────────────────────────────────────────────────────────
# DB write helpers
# ─────────────────────────────────────────────────────────────────────────────

def insert_evento(conn, evento: dict, fonte_id: int) -> Optional[int]:
    """Insert evento if not already present; update timestamp if it is.

    Return values (semantica invariata):
      - Positive int (evento id): new event inserted
      - Negative int (-evento id): existing event updated, luogo changed
      - 0: event already exists, only timestamp updated
      - None: internal error (should not occur under normal operation)

    Dedup strategy (story 3.7): chiave robusta (source_event_uid, id_fonte) con
    source_event_uid = sha256(titolo_normalizzato|data_inizio|id_fonte)[:32].
    Un singolo INSERT ... ON CONFLICT DO UPDATE garantisce atomicita ed evita
    il falso positivo strutturale della logica precedente basata su url_sorgente.
    """
    # Applica il fallback "Senza titolo" PRIMA del calcolo UID, cosi scraper e
    # backfill (che hasha il titolo persistito in DB) producono sempre lo stesso
    # uid anche per eventi con titolo mancante/vuoto (story 3.7 review fix C2).
    titolo = (evento.get("titolo") or "Senza titolo")[:500]
    data_inizio = evento.get("data_inizio")
    new_luogo = evento.get("luogo")
    tipo_evento_val = evento.get("tipo_evento", "altro")

    # Detection online: se titolo/tipo suggeriscono evento online ma lo scraper
    # ha assegnato un luogo fisico (es. indirizzo dell'organizzatore), forza
    # luogo='online' per evitare che compaia sulla mappa nella citta dell'ente.
    if _is_likely_online(titolo, tipo_evento_val, new_luogo):
        new_luogo = "online"
        evento["luogo"] = "online"
        evento["lat"] = None
        evento["lng"] = None

    source_event_uid = _make_source_event_uid(titolo, data_inizio, fonte_id)

    with conn.cursor() as cur:
        # Pre-fetch per detection luogo_changed. Lo scraper e single-process
        # (spawn da cron / endpoint HTTP unico) → no race tra SELECT e INSERT.
        # TODO: se in futuro lo scraper diventa multi-worker, sostituire il
        # pre-fetch con un SELECT post-upsert (usando xmax=0 per discriminare
        # INSERT/UPDATE) e portare il confronto luogo in SQL.
        cur.execute(
            "SELECT id, luogo FROM evento WHERE source_event_uid = %s AND id_fonte = %s",
            (source_event_uid, fonte_id),
        )
        existing = cur.fetchone()

        # Upsert atomico su (source_event_uid, id_fonte).
        cur.execute(
            """
            INSERT INTO evento (
                titolo, data_inizio, data_fine, luogo, lat, lng,
                tipo_evento, organizzatore, crediti_formativi,
                url_sorgente, id_fonte, mercato, source_event_uid,
                data_inserimento, data_ultimo_aggiornamento
            ) VALUES (
                %(titolo)s, %(data_inizio)s, %(data_fine)s, %(luogo)s, %(lat)s, %(lng)s,
                %(tipo_evento)s, %(organizzatore)s, %(crediti_formativi)s,
                %(url_sorgente)s, %(id_fonte)s, %(mercato)s, %(source_event_uid)s,
                NOW(), NOW()
            )
            ON CONFLICT (source_event_uid, id_fonte) DO UPDATE SET
                data_ultimo_aggiornamento = NOW()
            RETURNING id, (xmax = 0) AS inserted
            """,
            {
                "titolo": titolo,
                "data_inizio": data_inizio,
                "data_fine": evento.get("data_fine"),
                "luogo": new_luogo,
                "lat": evento.get("lat"),
                "lng": evento.get("lng"),
                "tipo_evento": evento.get("tipo_evento", "altro"),
                "organizzatore": evento.get("organizzatore"),
                "crediti_formativi": evento.get("crediti_formativi"),
                "url_sorgente": evento.get("url_sorgente"),
                "id_fonte": fonte_id,
                "mercato": evento.get("mercato", "italia"),
                "source_event_uid": source_event_uid,
            },
        )
        evento_id, was_inserted = cur.fetchone()

        if was_inserted:
            return_value = evento_id
        else:
            # Update path: confronto luogo normalizzato per decidere se invalidare geocoding.
            old_luogo = existing[1] if existing else None
            luogo_changed = _normalize_title(old_luogo) != _normalize_title(new_luogo)
            if luogo_changed:
                cur.execute(
                    "UPDATE evento SET luogo = %s, lat = NULL, lng = NULL WHERE id = %s",
                    (new_luogo, evento_id),
                )
                return_value = -evento_id
            else:
                return_value = 0

        cur.execute(
            """
            INSERT INTO opportunita (id_evento, stato, data_ultimo_aggiornamento)
            VALUES (%s, 'non_contattato', NOW())
            ON CONFLICT DO NOTHING
            """,
            (evento_id,),
        )

    conn.commit()
    return return_value

def geocode_and_update(conn, evento_id: int, luogo: str, paese: str = "Italia"):
    lat, lng = geocode_luogo(luogo, paese)
    with conn.cursor() as cur:
        if lat is not None:
            cur.execute(
                "UPDATE evento SET lat=%s, lng=%s, geocoding_attempted_at=NOW() WHERE id=%s",
                (lat, lng, evento_id)
            )
        else:
            cur.execute(
                "UPDATE evento SET geocoding_attempted_at=NOW() WHERE id=%s",
                (evento_id,)
            )
    conn.commit()
    return lat, lng


# Sources where a parseable date is required; NULL-date rows from these are deleted.
MANDATORY_DATE_FONTI: frozenset[str] = frozenset({
    "ISI Formazione",
    "CNF Calendario",
    "Camera Civile di Rimini",
})


def cleanup_noise_events(conn) -> int:
    """Remove noise events and fix NULL dates where the date is embedded in the title.

    Removal criteria (applied in order, first match wins):
    1. Title fails is_valid_event() — clear UI/navigation garbage.
    2. data_inizio is NULL AND a date is extractable from the title → UPDATE.
    3. data_inizio is NULL AND source in MANDATORY_DATE_FONTI → DELETE
       (these scrapers always produce dates; NULL means the page was malformed).
    4. data_inizio is NULL AND title has no event keyword → DELETE.

    Returns the number of rows deleted (not counting updated rows).
    """
    log.info("Cleanup: fetching events to evaluate...")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.id, e.titolo, e.data_inizio, f.nome
            FROM evento e
            JOIN fonte f ON f.id = e.id_fonte
            """
        )
        rows = cur.fetchall()

    to_delete: list[int] = []
    to_update: list[tuple[str, int]] = []

    for evento_id, titolo, data_inizio, fonte_nome in rows:
        titolo = titolo or ""

        if not is_valid_event(titolo, data_inizio):
            log.info(f"  Cleanup: removing noise id={evento_id} title={titolo!r}")
            to_delete.append(evento_id)
            continue

        if data_inizio is None:
            extracted = parse_date_from_text(titolo)
            has_keyword = bool(EVENT_KEYWORDS.search(titolo))
            mandatory = fonte_nome in MANDATORY_DATE_FONTI
            if extracted:
                log.info(f"  Cleanup: fixing date id={evento_id} title={titolo[:60]!r} → {extracted}")
                to_update.append((extracted, evento_id))
            elif mandatory:
                log.info(
                    f"  Cleanup: removing mandatory-source no-date id={evento_id} "
                    f"source={fonte_nome!r} title={titolo[:60]!r}"
                )
                to_delete.append(evento_id)
            elif not has_keyword:
                log.info(f"  Cleanup: removing no-date/no-keyword id={evento_id} title={titolo[:60]!r}")
                to_delete.append(evento_id)

    if to_update:
        with conn.cursor() as cur:
            for date_str, eid in to_update:
                with conn.cursor() as inner:
                    inner.execute("SELECT titolo FROM evento WHERE id = %s", (eid,))
                    row = inner.fetchone()
                cleaned_title = _clean_date_prefix(row[0]) if row else None
                if cleaned_title and cleaned_title != row[0]:
                    cur.execute(
                        "UPDATE evento SET data_inizio = %s, titolo = %s, data_ultimo_aggiornamento = NOW() WHERE id = %s",
                        (date_str, cleaned_title[:500], eid)
                    )
                else:
                    cur.execute(
                        "UPDATE evento SET data_inizio = %s, data_ultimo_aggiornamento = NOW() WHERE id = %s",
                        (date_str, eid)
                    )
        conn.commit()
        log.info(f"Cleanup: updated dates for {len(to_update)} events.")

    # Strip date prefixes from ALL existing titles (idempotent)
    _cleanup_title_prefixes(conn)

    if not to_delete:
        log.info("Cleanup: no events to delete.")
        return 0

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM opportunita WHERE id_evento = ANY(%s)",
            (to_delete,)
        )
        cur.execute(
            "DELETE FROM evento WHERE id = ANY(%s)",
            (to_delete,)
        )
    conn.commit()
    log.info(f"Cleanup: removed {len(to_delete)} noise events.")
    return len(to_delete)


def _cleanup_title_prefixes(conn) -> None:
    """Strip embedded date prefixes from event titles (idempotent)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, titolo FROM evento")
        rows = cur.fetchall()

    updates: list[tuple[str, int]] = []
    for eid, titolo in rows:
        cleaned = _clean_date_prefix(titolo or "")
        if cleaned and cleaned != titolo:
            updates.append((cleaned[:500], eid))

    if not updates:
        return

    with conn.cursor() as cur:
        for new_title, eid in updates:
            cur.execute(
                "UPDATE evento SET titolo = %s, data_ultimo_aggiornamento = NOW() WHERE id = %s",
                (new_title, eid)
            )
    conn.commit()
    log.info(f"Cleanup: cleaned date-prefix from {len(updates)} event titles.")


def cleanup_old_events(conn, days: int = 30) -> int:
    """Delete events whose end date (or start date if no end date) is older than `days` days ago.

    Returns the number of events deleted.
    """
    cutoff = date.today() - timedelta(days=days)
    cutoff_str = cutoff.isoformat()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM evento
            WHERE (
                data_fine IS NOT NULL AND data_fine < %s
            ) OR (
                data_fine IS NULL AND data_inizio IS NOT NULL
                AND data_inizio < %s
            )
            """,
            (cutoff_str, cutoff_str)
        )
        rows = cur.fetchall()

    to_delete = [row[0] for row in rows]
    if not to_delete:
        log.info(f"Old-events cleanup: no events older than {days} days found.")
        return 0

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM opportunita WHERE id_evento = ANY(%s)",
            (to_delete,)
        )
        cur.execute(
            "DELETE FROM evento WHERE id = ANY(%s)",
            (to_delete,)
        )
    conn.commit()
    log.info(f"Old-events cleanup: removed {len(to_delete)} events older than {days} days.")
    return len(to_delete)


# ─────────────────────────────────────────────────────────────────────────────
# Scrapers
# ─────────────────────────────────────────────────────────────────────────────
# Each scraper returns (inserted: int, updated: int, had_error: bool).

_RE_ISI_ORDINE = re.compile(
    r"Ordine\s+(?:degli\s+)?Avvocati\s+(?:di\s+)?([A-Za-zÀ-ÿ\s]+?)(?:\s+\d|\s*$)", re.IGNORECASE
)


def scrape_isi_formazione(conn, fonte_id: int) -> tuple[int, int, bool]:
    """ISI Formazione — accredited legal training events for Avvocati.

    The site was redesigned (2025) and now renders events as Bootstrap cards
    (class: .card.box-shadow2-Tinexta) instead of a table. Events are paginated
    via &PagRis=N. Each card contains:
      - h5.card-title.text-primary  → event title
      - span.font-weight-bold       → date (DD/MM/YYYY)
      - Card body text              → organiser (Ordine degli Avvocati di X)
      - .lnkCopiaLinkEvento         → direct event URL
    """
    log.info("Scraping ISI Formazione (redesigned card layout)...")
    base_url = "https://www.isiformazione.it/ita/_V2.0_risultatiricerca.asp"
    params_base = "?TipoOrdine=Avvocati&Luogo=Tutti"

    inserted = 0
    updated = 0
    had_error = False

    for page in range(1, 15):
        url = base_url + params_base + (f"&PagRis={page}" if page > 1 else "")
        log.info(f"  ISI page {page}: {url}")
        soup = fetch_html(url)
        sleep()

        if soup is None:
            log.warning(f"  ISI: failed to fetch page {page}")
            update_fonte_status(conn, fonte_id, False)
            return inserted, updated, True

        cards = soup.select(".card.box-shadow2-Tinexta")
        if not cards:
            log.info(f"  ISI: no cards on page {page}, stopping.")
            break

        log.info(f"  ISI page {page}: {len(cards)} cards")
        page_inserted = 0

        for card in cards:
            try:
                title_tag = card.select_one("h5.card-title")
                if not title_tag:
                    continue
                titolo = title_tag.get_text(strip=True)

                if not is_valid_event(titolo):
                    continue

                date_span = card.select_one("span.font-weight-bold")
                data_text = date_span.get_text(strip=True) if date_span else ""
                data_inizio = parse_date_from_text(data_text) or parse_date_from_text(titolo)
                if data_inizio is None:
                    log.debug(f"  ISI: no date for {titolo[:60]!r}")
                    continue

                card_text = card.get_text(" ", strip=True)
                luogo_text = None
                m = _RE_ISI_ORDINE.search(card_text)
                if m:
                    luogo_text = m.group(1).strip().title()

                link_tag = card.select_one(".lnkCopiaLinkEvento")
                link = None
                if link_tag and link_tag.get("href"):
                    href = link_tag["href"]
                    link = href if href.startswith("http") else "https://www.isiformazione.it/ita/" + href.lstrip("/")

                crediti = None
                m2 = re.search(r"Crediti:\s*(\d+)", card_text)
                if m2:
                    crediti = int(m2.group(1))

                evento = {
                    "titolo": titolo[:500],
                    "data_inizio": data_inizio,
                    "luogo": luogo_text or "Italia",
                    "tipo_evento": "corso_formativo",
                    "organizzatore": "ISI Formazione",
                    "crediti_formativi": crediti,
                    "url_sorgente": link or url,
                    "mercato": "italia",
                }

                result = insert_evento(conn, evento, fonte_id)
                if result is not None and result > 0:
                    if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                        geocode_and_update(conn, result, luogo_text)
                    inserted += 1
                    page_inserted += 1
                elif result is not None and result < 0:
                    updated += 1
                elif result == 0:
                    updated += 1

            except Exception as e:
                log.debug(f"  ISI card parse error: {e}")
                continue

        if page_inserted == 0 and page > 1:
            log.info(f"  ISI: no new events on page {page}, stopping.")
            break

    log.info(f"ISI Formazione: {inserted} new, {updated} updated")
    update_fonte_status(conn, fonte_id, True)
    return inserted, updated, False


def scrape_cnf(conn, fonte_id: int) -> tuple[int, int, bool]:
    """CNF Calendario — Consiglio Nazionale Forense events calendar.

    The page uses a Liferay CMS with Bootstrap card components:
      - .card-event           → each event card
      - .card-event__title    → event title (a tag)
      - .card-event__date     → date string (Italian, e.g. "27 marzo 2026")
      - .card-event__place    → location string
    """
    log.info("Scraping CNF Calendario...")
    url = "https://www.consiglionazionaleforense.it/web/cnf-news/calendario-eventi"
    soup = fetch_html(url)
    sleep()

    if soup is None:
        log.warning("CNF: fetch failed")
        update_fonte_status(conn, fonte_id, False)
        return 0, 0, True

    inserted = 0
    updated = 0

    cards = soup.select(".card-event")
    log.info(f"  CNF: found {len(cards)} card-event items")

    for card in cards:
        try:
            title_tag = card.select_one(".card-event__title")
            if not title_tag:
                continue
            titolo = title_tag.get_text(strip=True)
            if not is_valid_event(titolo):
                continue

            date_el = card.select_one(".card-event__date")
            date_text = date_el.get_text(" ", strip=True) if date_el else ""
            data_inizio = parse_date_from_text(date_text)
            if data_inizio is None:
                log.debug(f"  CNF: no date for {titolo[:60]!r} (raw: {date_text[:40]!r})")
                continue

            place_el = card.select_one(".card-event__place")
            luogo_text = place_el.get_text(strip=True) if place_el else None
            if luogo_text:
                luogo_text = re.sub(r"\s+", " ", luogo_text).strip()
                if len(luogo_text) > 100:
                    luogo_text = luogo_text[:100]

            link_tag = card.select_one("a[href]")
            link = None
            if link_tag:
                href = link_tag["href"]
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    link = "https://www.consiglionazionaleforense.it" + href

            evento = {
                "titolo": titolo[:500],
                "data_inizio": data_inizio,
                "luogo": luogo_text,
                "tipo_evento": "convegno",
                "organizzatore": "Consiglio Nazionale Forense",
                "url_sorgente": link or url,
                "mercato": "italia",
            }

            result = insert_evento(conn, evento, fonte_id)
            if result is not None and result > 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, result, luogo_text)
                inserted += 1
            elif result is not None and result < 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, abs(result), luogo_text)
                updated += 1
            elif result == 0:
                updated += 1

        except Exception as e:
            log.debug(f"CNF parse error: {e}")
            continue

    log.info(f"CNF: {inserted} new, {updated} updated")
    update_fonte_status(conn, fonte_id, True)
    return inserted, updated, False


def scrape_camera_civile_rimini(conn, fonte_id: int) -> tuple[int, int, bool]:
    """Camera Civile di Rimini — formazione events.

    Many titles embed the date as 'gg MESE aaaa — titolo' or similar.
    Events without an extractable date are skipped.
    """
    log.info("Scraping Camera Civile di Rimini...")
    url = "https://www.cameracivilerimini.it/formazione/"
    soup = fetch_html(url)
    sleep()

    if soup is None:
        log.warning("Camera Civile Rimini: fetch failed")
        update_fonte_status(conn, fonte_id, False)
        return 0, 0, True

    inserted = 0
    updated = 0

    items = (
        soup.select(".post") or
        soup.select("article") or
        soup.select(".entry") or
        soup.select("h2 a, h3 a")
    )

    log.info(f"  Camera Civile Rimini: found {len(items)} items")
    for item in items[:30]:
        try:
            title_tag = item.find(["h1", "h2", "h3", "h4"]) or item
            titolo_raw = title_tag.get_text(strip=True)
            if not is_valid_event(titolo_raw):
                continue

            data_inizio = extract_date_from_element(item)
            if data_inizio is None:
                data_inizio = parse_date_from_text(titolo_raw)
            if data_inizio is None:
                log.debug(f"  Camera Civile: skipping (no date): {titolo_raw[:60]!r}")
                continue

            titolo = _clean_date_prefix(titolo_raw)

            link_tag = item.find("a", href=True)
            link = None
            if link_tag:
                href = link_tag["href"]
                if href.startswith("http"):
                    link = href

            luogo_text = _extract_luogo_from_element(item)
            log.debug(f"  Camera Civile: luogo extracted: {luogo_text!r} for {titolo[:60]!r}")

            # Cascata fallback: estrazione DOM → check FAD/online nel titolo → "Rimini"
            if luogo_text is None:
                if any(kw in titolo_raw.lower() for kw in _ONLINE_KEYWORDS):
                    luogo_text = "online"
                else:
                    luogo_text = "Rimini"

            evento = {
                "titolo": titolo[:500],
                "data_inizio": data_inizio,
                "luogo": luogo_text,
                "tipo_evento": "corso_formativo",
                "organizzatore": "Camera Civile di Rimini",
                "url_sorgente": link or url,
                "mercato": "italia",
            }

            result = insert_evento(conn, evento, fonte_id)
            if result is not None and result > 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, result, luogo_text)
                inserted += 1
            elif result is not None and result < 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, abs(result), luogo_text)
                updated += 1
            elif result == 0:
                updated += 1

        except Exception as e:
            log.debug(f"Camera Civile Rimini parse error: {e}")
            continue

    log.info(f"Camera Civile Rimini: {inserted} new, {updated} updated")
    update_fonte_status(conn, fonte_id, True)
    return inserted, updated, False


_RE_DATE_PREFIX = re.compile(
    r"^\s*\d{1,2}\s+(?:" + _MESI_PATTERN + r")\s+\d{4}\s*[–—\-:]\s*",
    re.IGNORECASE,
)
_RE_DATE_SUFFIX = re.compile(
    r"\s*[–—\-]\s*\d{1,2}\s+(?:" + _MESI_PATTERN + r")\s+\d{4}\s*$",
    re.IGNORECASE,
)


def _clean_date_prefix(titolo: str) -> str:
    """Strip leading/trailing date fragments from a title string."""
    titolo = _RE_DATE_PREFIX.sub("", titolo).strip()
    titolo = _RE_DATE_SUFFIX.sub("", titolo).strip()
    return titolo or titolo


def scrape_legaltech_source(conn, fonte_id: int, nome: str, url: str, mercato: str = "italia") -> tuple[int, int, bool]:
    """Generic scraper for legaltech / association sources.

    Improvements over the original:
    - Noise filter: skips titles that fail is_valid_event()
    - Date extraction: tries to find a date in each element
    - Quality gate: skips items with no date AND no event keyword in title
    """
    log.info(f"Scraping {nome}...")
    soup = fetch_html(url)
    sleep()

    if soup is None:
        log.warning(f"{nome}: fetch failed")
        update_fonte_status(conn, fonte_id, False)
        return 0, 0, True

    inserted = 0
    updated = 0

    items = (
        soup.select(".event") or
        soup.select("article") or
        soup.select(".agenda-item") or
        soup.select(".event-card") or
        soup.select(".wp-block-post") or
        soup.select("h2, h3")
    )

    log.info(f"  {nome}: found {len(items)} candidate items")
    skipped_noise = 0
    skipped_no_date = 0

    for item in items[:30]:
        try:
            title_tag = item.find(["h1", "h2", "h3", "h4", "a"]) if hasattr(item, "find") else item
            if title_tag is None:
                continue
            titolo = title_tag.get_text(strip=True)

            if not is_valid_event(titolo):
                skipped_noise += 1
                log.debug(f"  {nome}: noise skip: {titolo[:60]!r}")
                continue

            data_inizio = extract_date_from_element(item)
            has_event_keyword = bool(EVENT_KEYWORDS.search(titolo))

            if data_inizio is None and not has_event_keyword:
                skipped_no_date += 1
                log.debug(f"  {nome}: no date/keyword skip: {titolo[:60]!r}")
                continue

            link_tag = item.find("a", href=True) if hasattr(item, "find") else None
            link = None
            if link_tag:
                href = link_tag["href"]
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    parsed = urlparse(url)
                    link = f"{parsed.scheme}://{parsed.netloc}{href}"

            # Estrazione luogo: DOM → keywords online nel titolo → fallback per fonte
            luogo_text = _extract_luogo_from_element(item)
            log.debug(f"  {nome}: luogo extracted: {luogo_text!r} for {titolo[:60]!r}")

            if luogo_text is None:
                if any(kw in titolo.lower() for kw in _ONLINE_KEYWORDS):
                    luogo_text = "online"
                else:
                    # Per fonti senza default (AIGA, ANF) restituisce None → evento non sulla mappa
                    luogo_text = _LEGALTECH_DEFAULT_LOCATION.get(nome)

            tipo = (
                "fiera_legaltech"
                if "legaltech" in nome.lower() or "legal tech" in nome.lower()
                else "convegno"
            )

            evento = {
                "titolo": titolo[:500],
                "data_inizio": data_inizio,
                "luogo": luogo_text,
                "tipo_evento": tipo,
                "organizzatore": nome,
                "url_sorgente": link or url,
                "mercato": mercato,
            }

            # Determinare paese per geocoding
            paese_geo = "internazionale" if mercato == "internazionale" else "Italia"

            result = insert_evento(conn, evento, fonte_id)
            if result is not None and result > 0:
                # Evento nuovo
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, result, luogo_text, paese_geo)
                inserted += 1
            elif result is not None and result < 0:
                # Evento esistente con luogo cambiato — re-geocode
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, abs(result), luogo_text, paese_geo)
                updated += 1
            elif result == 0:
                updated += 1

        except Exception as e:
            log.debug(f"{nome} parse error: {e}")
            continue

    log.info(
        f"{nome}: {inserted} new, {updated} updated "
        f"(skipped: {skipped_noise} noise, {skipped_no_date} no date/keyword)"
    )
    update_fonte_status(conn, fonte_id, True)
    return inserted, updated, False


def _iba_stable_url(base: str, titolo: str, data_inizio: str) -> str:
    """Return a stable per-event URL for IBA events (which have no individual page links).

    Appends a short MD5-based fragment so insert_evento URL-dedup treats each
    (title, date) pair as a distinct entry across multiple scraper runs.
    """
    import hashlib
    key = f"{titolo.lower().strip()}|{data_inizio}"
    fragment = hashlib.md5(key.encode()).hexdigest()[:8]
    return f"{base}#{fragment}"


def scrape_iba(conn, fonte_id: int) -> tuple[int, int, bool]:
    """IBA (International Bar Association) conferences and events.

    URL: ibanet.org/conferences
    Each event is a .conferenceContent card-body div containing:
      - h5.card-title.text-ellipsis  → event title
      - first p.card-text.mb-2       → date text (e.g. "08 Apr 2026" or "09 Apr - 10 Apr 2026")
      - second p.card-text.mb-0      → location ("Tokyo, Japan") or "Webinar"
    The page shows 30 upcoming events sorted by start date.
    """
    log.info("Scraping IBA conferences...")
    url = "https://www.ibanet.org/conferences"
    soup = fetch_html(url)
    sleep()

    if soup is None:
        log.warning("IBA: fetch failed")
        update_fonte_status(conn, fonte_id, False)
        return 0, 0, True

    inserted = 0
    updated = 0

    items = soup.select(".conferenceContent")
    log.info(f"  IBA: found {len(items)} conferenceContent items")

    for item in items:
        try:
            title_tag = item.select_one("h5.card-title, h5")
            if not title_tag:
                continue
            titolo = title_tag.get_text(strip=True)
            if not is_valid_event(titolo):
                continue

            date_paras = item.select("p.card-text")
            date_text = date_paras[0].get_text(" ", strip=True) if date_paras else ""
            data_inizio = parse_date_from_text(date_text)
            if data_inizio is None:
                log.debug(f"  IBA: no date for {titolo[:60]!r}")
                continue

            luogo_text = None
            if len(date_paras) > 1:
                raw_loc = re.sub(r"\s+", " ", date_paras[1].get_text(" ", strip=True)).strip()
                if "webinar" in raw_loc.lower():
                    luogo_text = "online"
                elif raw_loc:
                    city_part = raw_loc.split(",")[0].strip()
                    luogo_text = city_part if city_part else raw_loc

            evento = {
                "titolo": titolo[:500],
                "data_inizio": data_inizio,
                "luogo": luogo_text,
                "tipo_evento": "convegno",
                "organizzatore": "IBA",
                "url_sorgente": _iba_stable_url(url, titolo, data_inizio),
                "mercato": "internazionale",
            }

            result = insert_evento(conn, evento, fonte_id)
            if result is not None and result > 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, result, luogo_text, "internazionale")
                inserted += 1
            elif result is not None and result < 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, abs(result), luogo_text, "internazionale")
                updated += 1
            elif result == 0:
                updated += 1

        except Exception as e:
            log.debug(f"IBA parse error: {e}")
            continue

    log.info(f"IBA: {inserted} new, {updated} updated")
    update_fonte_status(conn, fonte_id, True)
    return inserted, updated, False


def scrape_aba(conn, fonte_id: int) -> tuple[int, int, bool]:
    """ABA (American Bar Association) CLE events and meetings.

    URL: https://www.americanbar.org/events-cle/
    Typical structure: article/li items with class containing "event" or Bootstrap cards.
    ABA uses a standard CMS with event cards showing title, date, location.
    """
    log.info("Scraping ABA events...")
    url = "https://www.americanbar.org/events-cle/"
    soup = fetch_html(url)
    sleep()

    if soup is None:
        log.warning("ABA: fetch failed")
        update_fonte_status(conn, fonte_id, False)
        return 0, 0, True

    inserted = 0
    updated = 0

    candidates = (
        soup.select(".event-item") or
        soup.select("article.event") or
        soup.select(".events-listing__item") or
        soup.select(".card-event") or
        soup.select("li.event") or
        soup.select(".aba-event")
    )
    if not candidates:
        candidates = soup.select("article, .card")

    log.info(f"  ABA: found {len(candidates)} candidate items")

    for item in candidates[:60]:
        try:
            title_tag = item.select_one("h2, h3, h4, .event-title, .card-title, a")
            if not title_tag:
                continue
            titolo = title_tag.get_text(strip=True)
            if not is_valid_event(titolo):
                continue

            data_inizio = extract_date_from_element(item) or parse_date_from_text(item.get_text(" "))
            if data_inizio is None:
                continue

            link_tag = item.select_one("a[href]") or item.find_parent("a", href=True)
            link = None
            if link_tag:
                href = link_tag["href"]
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    link = "https://www.americanbar.org" + href

            luogo_text = _extract_luogo_from_element(item)

            evento = {
                "titolo": titolo[:500],
                "data_inizio": data_inizio,
                "luogo": luogo_text,
                "tipo_evento": "convegno",
                "organizzatore": "ABA",
                "url_sorgente": link or url,
                "mercato": "internazionale",
            }

            result = insert_evento(conn, evento, fonte_id)
            if result is not None and result > 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, result, luogo_text, "internazionale")
                inserted += 1
            elif result is not None and result < 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, abs(result), luogo_text, "internazionale")
                updated += 1
            elif result == 0:
                updated += 1

        except Exception as e:
            log.debug(f"ABA parse error: {e}")
            continue

    log.info(f"ABA: {inserted} new, {updated} updated")
    update_fonte_status(conn, fonte_id, True)
    return inserted, updated, False


def scrape_inta(conn, fonte_id: int) -> tuple[int, int, bool]:
    """INTA (International Trademark Association) events.

    URL: https://www.inta.org/events/
    INTA uses Bootstrap card components for their events listing:
      - .card or .event-card wrapper
      - .card-title or h3/h4 for title
      - Date often in .card-text, time tag, or span with date class
      - Location in a city/country span
    """
    log.info("Scraping INTA events...")
    url = "https://www.inta.org/events/"
    soup = fetch_html(url)
    sleep()

    if soup is None:
        log.warning("INTA: fetch failed")
        update_fonte_status(conn, fonte_id, False)
        return 0, 0, True

    inserted = 0
    updated = 0

    candidates = (
        soup.select(".event-card") or
        soup.select(".card.event") or
        soup.select("article.event") or
        soup.select(".events__item") or
        soup.select(".card")
    )
    if not candidates:
        candidates = soup.select("article, li.event-item")

    log.info(f"  INTA: found {len(candidates)} candidate items")

    for item in candidates[:60]:
        try:
            title_tag = item.select_one("h2, h3, h4, .card-title, .event-title, a")
            if not title_tag:
                continue
            titolo = title_tag.get_text(strip=True)
            if not is_valid_event(titolo):
                continue

            data_inizio = extract_date_from_element(item) or parse_date_from_text(item.get_text(" "))
            if data_inizio is None:
                continue

            link_tag = item.select_one("a[href]") or item.find_parent("a", href=True)
            link = None
            if link_tag:
                href = link_tag["href"]
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    link = "https://www.inta.org" + href

            luogo_text = _extract_luogo_from_element(item)

            evento = {
                "titolo": titolo[:500],
                "data_inizio": data_inizio,
                "luogo": luogo_text,
                "tipo_evento": "convegno",
                "organizzatore": "INTA",
                "url_sorgente": link or url,
                "mercato": "internazionale",
            }

            result = insert_evento(conn, evento, fonte_id)
            if result is not None and result > 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, result, luogo_text, "internazionale")
                inserted += 1
            elif result is not None and result < 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, abs(result), luogo_text, "internazionale")
                updated += 1
            elif result == 0:
                updated += 1

        except Exception as e:
            log.debug(f"INTA parse error: {e}")
            continue

    log.info(f"INTA: {inserted} new, {updated} updated")
    update_fonte_status(conn, fonte_id, True)
    return inserted, updated, False


def scrape_camera_arbitrale_milano(conn, fonte_id: int) -> tuple[int, int, bool]:
    """Camera Arbitrale di Milano — Italian arbitration chamber events.

    URL: https://www.camera-arbitrale.it/it/eventi/
    Typical structure: Bootstrap card components for events, with
    date badges and descriptive text.
    """
    log.info("Scraping Camera Arbitrale di Milano...")
    url = "https://www.camera-arbitrale.it/it/eventi/"
    soup = fetch_html(url)
    sleep()

    if soup is None:
        log.warning("Camera Arbitrale Milano: fetch failed")
        update_fonte_status(conn, fonte_id, False)
        return 0, 0, True

    inserted = 0
    updated = 0

    candidates = (
        soup.select(".event-card") or
        soup.select(".card-event") or
        soup.select("article.event") or
        soup.select(".evento") or
        soup.select(".card")
    )
    if not candidates:
        candidates = soup.select("article, .entry")

    log.info(f"  Camera Arbitrale Milano: found {len(candidates)} candidate items")

    for item in candidates[:50]:
        try:
            title_tag = item.select_one("h2, h3, h4, .card-title, .event-title, a")
            if not title_tag:
                continue
            titolo = title_tag.get_text(strip=True)
            if not is_valid_event(titolo):
                continue

            data_inizio = extract_date_from_element(item) or parse_date_from_text(item.get_text(" "))
            if data_inizio is None:
                continue

            link_tag = item.select_one("a[href]") or item.find_parent("a", href=True)
            link = None
            if link_tag:
                href = link_tag["href"]
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    link = "https://www.camera-arbitrale.it" + href

            luogo_text = _extract_luogo_from_element(item) or "Milano"

            evento = {
                "titolo": titolo[:500],
                "data_inizio": data_inizio,
                "luogo": luogo_text,
                "tipo_evento": "convegno",
                "organizzatore": "Camera Arbitrale di Milano",
                "url_sorgente": link or url,
                "mercato": "italia",
            }

            result = insert_evento(conn, evento, fonte_id)
            if result is not None and result > 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, result, luogo_text)
                inserted += 1
            elif result is not None and result < 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, abs(result), luogo_text)
                updated += 1
            elif result == 0:
                updated += 1

        except Exception as e:
            log.debug(f"Camera Arbitrale Milano parse error: {e}")
            continue

    log.info(f"Camera Arbitrale Milano: {inserted} new, {updated} updated")
    update_fonte_status(conn, fonte_id, True)
    return inserted, updated, False


def scrape_federprivacy(conn, fonte_id: int) -> tuple[int, int, bool]:
    """Federprivacy — Italian data protection and privacy law events.

    URL: https://www.federprivacy.org/eventi/
    Events are listed with Bootstrap card structure showing title, date, location.
    Data protection law events are highly relevant to the Italian legal sector.
    """
    log.info("Scraping Federprivacy eventi...")
    url = "https://www.federprivacy.org/eventi/"
    soup = fetch_html(url)
    sleep()

    if soup is None:
        log.warning("Federprivacy: fetch failed")
        update_fonte_status(conn, fonte_id, False)
        return 0, 0, True

    inserted = 0
    updated = 0

    candidates = (
        soup.select("article.evento") or
        soup.select(".evento") or
        soup.select("article.event") or
        soup.select(".card") or
        soup.select("article")
    )
    if not candidates:
        candidates = soup.select("li.event-item, .entry")

    log.info(f"  Federprivacy: found {len(candidates)} candidate items")

    for item in candidates[:60]:
        try:
            title_tag = item.select_one("h2, h3, h4, .entry-title, .card-title, .event-title, a")
            if not title_tag:
                continue
            titolo = title_tag.get_text(strip=True)
            if not is_valid_event(titolo):
                continue

            data_inizio = extract_date_from_element(item) or parse_date_from_text(item.get_text(" "))
            if data_inizio is None:
                continue

            link_tag = item.select_one("a[href]") or item.find_parent("a", href=True)
            link = None
            if link_tag:
                href = link_tag["href"]
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    link = "https://www.federprivacy.org" + href

            luogo_text = _extract_luogo_from_element(item)

            evento = {
                "titolo": titolo[:500],
                "data_inizio": data_inizio,
                "luogo": luogo_text,
                "tipo_evento": "convegno",
                "organizzatore": "Federprivacy",
                "url_sorgente": link or url,
                "mercato": "italia",
            }

            result = insert_evento(conn, evento, fonte_id)
            if result is not None and result > 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, result, luogo_text)
                inserted += 1
            elif result is not None and result < 0:
                if luogo_text and luogo_text.lower() not in _ONLINE_KEYWORDS:
                    geocode_and_update(conn, abs(result), luogo_text)
                updated += 1
            elif result == 0:
                updated += 1

        except Exception as e:
            log.debug(f"Federprivacy parse error: {e}")
            continue

    log.info(f"Federprivacy: {inserted} new, {updated} updated")
    update_fonte_status(conn, fonte_id, True)
    return inserted, updated, False


# --- Scraper registry: maps fonte nome → (scraper_type, url, mercato) ---
SCRAPER_REGISTRY: dict[str, tuple[str, Optional[str], Optional[str]]] = {
    "ISI Formazione":               ("isi",                    None,  "italia"),
    "CNF Calendario":               ("cnf",                    None,  "italia"),
    "Camera Civile di Rimini":      ("camera_civile",          None,  "italia"),
    "IBA":                          ("iba",                    None,  "internazionale"),
    "ABA":                          ("aba",                    None,  "internazionale"),
    "INTA":                         ("inta",                   None,  "internazionale"),
    "Camera Arbitrale di Milano":   ("camera_arbitrale_mi",    None,  "italia"),
    "Federprivacy":                 ("federprivacy",           None,  "italia"),
    "Legal Tech Forum":             ("llm",               "https://forum.legaltechitaly.com/",                "italia"),
    "GLTH Milano":                  ("llm",               "https://www.hublegaltech.com/agenda",              "italia"),
    "LegalTechTalk":                ("llm",               "https://www.legaltech-talk.com/",                  "internazionale"),
    "Lexpo":                        ("llm",               "https://lexpo.com/",                               "internazionale"),
    "AIGA":                         ("llm",               "https://www.aiga.it/",                             "italia"),
    "ANF":                          ("llm",               "https://www.associazionenazionaleforense.it/",     "italia"),
    "Scuola Forense Milano":        ("llm",               "https://www.scuolaforensemilano.it/servizi/formazione-continua/", "italia"),
    "Fondazione Forense Firenze":   ("llm",               "https://www.fondazioneforensefirenze.it/",         "italia"),
    "FEST Formazione Forense":      ("llm",               "https://fondazionest.com/events/",                 "italia"),
}

WORKER_TIMEOUT_SECONDS = 120  # Max seconds per fonte worker before timeout

# --- Main ---

def _dispatch_scraper(
    conn, fonte_id: int, nome: str, dry_run: bool = False
) -> tuple[int, int, bool]:
    """Dispatch to the right scraper function for the given fonte nome.

    Called from worker threads; each thread supplies its own `conn`.
    `dry_run` e rilevante solo per gli scraper che lo supportano (LLM).
    """
    if nome not in SCRAPER_REGISTRY:
        log.warning(f"No scraper registered for fonte '{nome}', skipping")
        return 0, 0, True

    scraper_type, url, mercato = SCRAPER_REGISTRY[nome]
    log.info(f"--- Processing: {nome} (id={fonte_id}){' [DRY-RUN]' if dry_run else ''} ---")

    if scraper_type == "isi":
        return scrape_isi_formazione(conn, fonte_id)
    elif scraper_type == "cnf":
        return scrape_cnf(conn, fonte_id)
    elif scraper_type == "camera_civile":
        return scrape_camera_civile_rimini(conn, fonte_id)
    elif scraper_type == "iba":
        return scrape_iba(conn, fonte_id)
    elif scraper_type == "aba":
        return scrape_aba(conn, fonte_id)
    elif scraper_type == "inta":
        return scrape_inta(conn, fonte_id)
    elif scraper_type == "camera_arbitrale_mi":
        return scrape_camera_arbitrale_milano(conn, fonte_id)
    elif scraper_type == "federprivacy":
        return scrape_federprivacy(conn, fonte_id)
    elif scraper_type == "llm":
        if url:
            from scraper.llm_scraper import scrape_with_llm  # lazy import
            return scrape_with_llm(conn, fonte_id, nome, url, mercato or "italia", dry_run=dry_run)
        log.warning(f"No URL configured for llm fonte '{nome}'")
        return 0, 0, True
    elif scraper_type == "legaltech_generic":
        # Fallback d'emergenza (G5 — rollback rapido story 3.10)
        if url:
            return scrape_legaltech_source(conn, fonte_id, nome, url, mercato or "italia")
        log.warning(f"No URL configured for legaltech_generic fonte '{nome}'")
        return 0, 0, True
    else:
        log.warning(f"Unknown scraper type '{scraper_type}' for '{nome}'")
        return 0, 0, True


def _scrape_fonte_worker(fonte_id: int, nome: str, dry_run: bool = False) -> tuple[str, int, int, bool]:
    """Worker function executed in a thread pool.

    Opens its own DB connection (psycopg2 connections are not thread-safe),
    runs the scraper, then closes it.

    Returns (nome, inserted, updated, had_error).
    """
    conn = get_conn()
    try:
        ins, upd, had_error = _dispatch_scraper(conn, fonte_id, nome, dry_run=dry_run)
        return nome, ins, upd, had_error
    except Exception as e:
        log.error(f"Scraper for '{nome}' raised an exception: {e}", exc_info=True)
        try:
            update_fonte_status(conn, fonte_id, False)
        except Exception:
            pass
        return nome, 0, 0, True
    finally:
        conn.close()


def run_scraper(cleanup: bool = False, dry_run: bool = False) -> dict:
    """Run the full scraping cycle over all active fonti in parallel.

    Args:
        cleanup: If True, first remove noise/garbage events from the DB.
        dry_run: If True, LLM scrapers log extracted events without writing DB
                 (story 3.10). Non-LLM scrapers ignore this flag.

    Returns a stats dict with keys:
      fonti_processed, inserted, updated, errors, failed_fonti, cleaned
    """
    log.info(f"=== Events Radar Scraper starting{' [DRY-RUN]' if dry_run else ''} ===")

    # Reset LLM call counter at run start (story 3.10)
    try:
        from scraper.llm_scraper import reset_counter as _llm_reset
        _llm_reset()
    except Exception:
        pass

    shared_conn = get_conn()

    cleaned = 0
    if cleanup:
        log.info("--- Running cleanup phase ---")
        cleaned = cleanup_noise_events(shared_conn)
        log.info(f"--- Cleanup done: {cleaned} removed ---")

    # Pre-warm geocode cache so threads skip Nominatim for known cities.
    prewarm_geocode_cache(shared_conn)

    active_fonti = get_active_fonti(shared_conn)
    shared_conn.close()
    log.info(f"Active fonti to scrape: {len(active_fonti)}")

    total_inserted = 0
    total_updated = 0
    total_errors = 0
    failed_fonti: list[str] = []
    fonti_processed = 0

    known_fonti = [
        (fid, nome) for fid, nome in active_fonti if nome in SCRAPER_REGISTRY
    ]

    if not known_fonti:
        log.info("No known fonti to scrape. Exiting early.")
        return {
            "fonti_processed": 0,
            "inserted": 0,
            "updated": 0,
            "errors": 0,
            "failed_fonti": [],
            "cleaned": cleaned,
        }

    # Run all sources in parallel; each worker manages its own DB connection.
    max_workers = min(len(known_fonti), 8)
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        future_map = {
            executor.submit(_scrape_fonte_worker, fonte_id, nome, dry_run): (fonte_id, nome)
            for fonte_id, nome in known_fonti
        }

        # Enforce an overall wall-clock deadline. Workers run concurrently
        # (max_workers up to 8), so the wall-clock for the slowest worker
        # ≈ WORKER_TIMEOUT_SECONDS. Using wait()+FIRST_COMPLETED instead of
        # as_completed() lets us actually time out on hung workers — with
        # as_completed(), future.result(timeout=...) is unreachable because
        # the yielded future has already finished.
        deadline = time.monotonic() + WORKER_TIMEOUT_SECONDS
        pending = set(future_map.keys())

        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                break  # timeout fired
            for future in done:
                fonte_id_f, nome_f = future_map[future]
                try:
                    result_nome, ins, upd, had_error = future.result()
                except Exception as e:
                    log.error(f"Future for '{nome_f}' raised: {e}", exc_info=True)
                    had_error = True
                    ins, upd = 0, 0
                    result_nome = nome_f

                total_inserted += ins
                total_updated += upd
                fonti_processed += 1
                if had_error:
                    total_errors += 1
                    failed_fonti.append(result_nome)

        # Any futures still pending past the deadline are treated as timeouts.
        # Note: Python threads can't be forcibly killed — hung workers continue
        # in the background until their own I/O timeouts fire. cancel_futures
        # at executor shutdown releases queued-but-not-started slots.
        for future in pending:
            fonte_id_f, nome_f = future_map[future]
            future.cancel()
            log.error(f"Worker for '{nome_f}' timed out after {WORKER_TIMEOUT_SECONDS}s")
            total_errors += 1
            fonti_processed += 1
            failed_fonti.append(nome_f)
            try:
                timeout_conn = get_conn()
                update_fonte_status(timeout_conn, fonte_id_f, False)
                timeout_conn.close()
            except Exception:
                log.error(f"Failed to update fonte status for '{nome_f}' after timeout")
    finally:
        # wait=False so the main thread isn't blocked on hung workers;
        # cancel_futures releases any queued-but-not-started tasks.
        executor.shutdown(wait=False, cancel_futures=True)

    log.info(
        f"=== Scraper finished. "
        f"Fonti: {fonti_processed}, "
        f"New: {total_inserted}, "
        f"Updated: {total_updated}, "
        f"Errors: {total_errors}, "
        f"Cleaned: {cleaned} ==="
    )

    return {
        "fonti_processed": fonti_processed,
        "inserted": total_inserted,
        "updated": total_updated,
        "errors": total_errors,
        "failed_fonti": failed_fonti,
        "cleaned": cleaned,
    }


if __name__ == "__main__":
    stats = run_scraper()
    if stats["errors"] > 0:
        sys.exit(1)
