"""Unit tests for scraper.scraper.is_valid_event (AC #3).

Verifies that known UI/navigation/footer text is classified as noise (False)
and that plausible event titles are classified as valid (True).
"""

from scraper.scraper import is_valid_event


# ─── Noise (should return False) ────────────────────────────────────────────


def test_noise_short_title():
    # Titles shorter than 15 chars are always noise.
    assert is_valid_event("Home") is False


def test_noise_only_numbers_and_symbols():
    assert is_valid_event("2026 --- 2026 ---") is False


def test_noise_nav_menu_word():
    # Bare navigation words are < 15 chars, so filtered by length guard.
    assert is_valid_event("Menu") is False
    assert is_valid_event("Login") is False
    assert is_valid_event("Contatti") is False


# Realistic noise strings >15 chars — these exercise the keyword-based
# filters (RE_NOISE_START / _NOISE_EXACT), NOT the length guard.


def test_noise_newsletter_cta_long():
    # Starts with "newsletter" → caught by RE_NOISE_START even at 20+ chars.
    assert is_valid_event("Newsletter mensile eventi legaltech") is False


def test_noise_clicca_cta_long():
    # Starts with "clicca" → caught by RE_NOISE_START.
    assert is_valid_event("Clicca qui per scoprire tutti i dettagli") is False


def test_noise_tutti_gli_eventi_long():
    # Starts with "tutti gli eventi" → RE_NOISE_START.
    assert is_valid_event("Tutti gli eventi del 2026 in programma") is False


def test_noise_archivio_prefix():
    # Starts with "archivio" → RE_NOISE_START.
    assert is_valid_event("Archivio eventi passati stagione 2024") is False


def test_noise_exact_prossimi_eventi():
    # Exactly matches _NOISE_EXACT entry "prossimi eventi" (15 chars, passes length guard).
    assert is_valid_event("prossimi eventi") is False


# ─── Valid event titles (should return True) ───────────────────────────────


def test_valid_long_event_title():
    title = "Convegno annuale sulla Giustizia Digitale e Legal Tech 2026"
    assert is_valid_event(title) is True


def test_valid_legaltech_conference_title():
    title = "Corso formativo avanzato su Intelligenza Artificiale e Diritto"
    assert is_valid_event(title) is True


def test_valid_webinar_title():
    title = "Webinar: Contrattualistica internazionale per studi legali"
    assert is_valid_event(title) is True
