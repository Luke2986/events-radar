#!/usr/bin/env python3
"""
Offline test per scraper LLM (story 3.10).

Per ogni fonte LLM:
- Legge HTML snapshot da scraper/tests/golden/<fonte>.html
- Esegue SOLO lo step di LLM extraction (cleaning + prompt + parse JSON)
  — NON fa fetch HTTP, NON scrive DB, NON fa geocoding
- Confronta eventi estratti con scraper/tests/golden/<fonte>_expected.json
- Richiede Levenshtein ratio >= 0.8 sul titolo (match fuzzy)
- Verifica che almeno l'80% degli eventi attesi siano trovati

Usage:
    export GEMINI_API_KEY=...
    python -m scraper.tests.test_llm_scraper

Exit code: 0 se tutti i test passano, 1 altrimenti.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import pytest

# Mark the entire module as `llm` so `pytest -m "not llm"` skips it by default.
# Running this file still requires GEMINI_API_KEY and live LLM calls.
pytestmark = pytest.mark.llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
log = logging.getLogger("test_llm_scraper")

GOLDEN_DIR = Path(__file__).parent / "golden"
MATCH_THRESHOLD_RATIO = 0.8
COVERAGE_THRESHOLD = 0.8

# (fonte_nome_for_prompt, snapshot_filename, fonte_url, mercato)
FONTI = [
    ("Legal Tech Forum", "legal_tech_forum", "https://forum.legaltechitaly.com/", "italia"),
    ("GLTH Milano", "glth_milano", "https://www.hublegaltech.com/agenda", "italia"),
    ("LegalTechTalk", "legaltechtalk", "https://www.legaltech-talk.com/", "internazionale"),
    ("Lexpo", "lexpo", "https://lexpo.com/", "internazionale"),
    ("AIGA", "aiga", "https://www.aiga.it/", "italia"),
    ("ANF", "anf", "https://www.associazionenazionaleforense.it/", "italia"),
]


def _normalize_title(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def _fuzzy_ratio(a: str, b: str) -> float:
    try:
        import Levenshtein  # type: ignore
        return Levenshtein.ratio(a, b)
    except ImportError:
        # Fallback substring-based score
        a_norm = _normalize_title(a)
        b_norm = _normalize_title(b)
        if not a_norm or not b_norm:
            return 0.0
        if a_norm == b_norm:
            return 1.0
        if a_norm in b_norm or b_norm in a_norm:
            return 0.9
        # Dice coefficient as last resort
        a_set = set(a_norm.split())
        b_set = set(b_norm.split())
        if not a_set or not b_set:
            return 0.0
        common = len(a_set & b_set)
        return 2 * common / (len(a_set) + len(b_set))


def _extract_from_snapshot(html_path: Path, nome: str, url: str, mercato: str) -> list[dict]:
    """Invoca SOLO lo step LLM (cleaning + call Gemini + parse) su HTML da file."""
    from bs4 import BeautifulSoup
    from scraper.llm_scraper import (
        _clean_html_for_llm,
        _extract_events_from_html,
        reset_counter,
    )

    # Configura genai (idempotente)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set — cannot run extraction tests")
    import google.generativeai as genai
    genai.configure(api_key=api_key)

    html_bytes = html_path.read_bytes()
    soup = BeautifulSoup(html_bytes, "lxml")
    cleaned = _clean_html_for_llm(soup)
    result = _extract_events_from_html(cleaned, nome, url)
    if result.get("_cap_reached"):
        log.warning(f"{nome}: LLM cap reached during test extraction")
    return result.get("events", [])


def _find_match(expected_titolo: str, extracted: list[dict]) -> Optional[dict]:
    best = None
    best_ratio = 0.0
    exp_norm = _normalize_title(expected_titolo)
    for ev in extracted:
        got_norm = _normalize_title(ev.get("titolo", ""))
        ratio = _fuzzy_ratio(exp_norm, got_norm)
        if ratio > best_ratio:
            best_ratio = ratio
            best = ev
    if best_ratio >= MATCH_THRESHOLD_RATIO:
        return best
    return None


def _run_one_fonte(nome: str, slug: str, url: str, mercato: str) -> tuple[bool, str]:
    """Return (passed, reason)."""
    html_path = GOLDEN_DIR / f"{slug}.html"
    exp_path = GOLDEN_DIR / f"{slug}_expected.json"
    if not html_path.exists():
        return False, f"missing snapshot {html_path}"
    if not exp_path.exists():
        return False, f"missing expected {exp_path}"

    expected = json.loads(exp_path.read_text())
    expected_events = expected.get("events", [])

    log.info(f"--- {nome}: extracting from {html_path.name} ---")
    try:
        extracted = _extract_from_snapshot(html_path, nome, url, mercato)
    except Exception as e:
        return False, f"extraction failed: {type(e).__name__}: {e}"

    log.info(f"    extracted: {len(extracted)} events, expected: {len(expected_events)}")

    if not expected_events:
        # Snapshot senza eventi visibili — AC 80% non si applica
        note = expected.get("note", "")
        log.info(f"    [SKIP coverage check] — {note}")
        return True, "no expected events (snapshot sans events)"

    matched = 0
    for exp_ev in expected_events:
        exp_titolo = exp_ev.get("titolo", "")
        match = _find_match(exp_titolo, extracted)
        if match:
            matched += 1
            log.info(f"    ✓ matched: {exp_titolo!r} ~ {match.get('titolo')!r}")
        else:
            log.warning(f"    ✗ missing: {exp_titolo!r}")

    coverage = matched / len(expected_events)
    log.info(f"    coverage: {matched}/{len(expected_events)} = {coverage:.0%}")
    if coverage >= COVERAGE_THRESHOLD:
        return True, f"coverage {coverage:.0%} >= {COVERAGE_THRESHOLD:.0%}"
    return False, f"coverage {coverage:.0%} < {COVERAGE_THRESHOLD:.0%}"


def test_all_sources() -> int:
    from scraper.llm_scraper import reset_counter
    reset_counter()

    results: list[tuple[str, bool, str]] = []
    for nome, slug, url, mercato in FONTI:
        passed, reason = _run_one_fonte(nome, slug, url, mercato)
        results.append((nome, passed, reason))

    log.info("=" * 60)
    log.info("  TEST SUMMARY")
    log.info("=" * 60)
    all_passed = True
    for nome, passed, reason in results:
        status = "PASS" if passed else "FAIL"
        log.info(f"  [{status}] {nome}: {reason}")
        if not passed:
            all_passed = False
    log.info("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(test_all_sources())
