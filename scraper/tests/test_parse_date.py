"""Unit tests for scraper.scraper.parse_date_from_text.

Coverage (AC #3):
- ISO format `YYYY-MM-DD`
- Slash / dash format `dd/MM/yyyy` (Italian convention)
- Italian textual format (`12 marzo 2026`)
- Pre-2024 cutoff: dates before 2024-01-01 must return None
"""

from scraper.scraper import parse_date_from_text


def test_iso_format_returns_iso_string():
    assert parse_date_from_text("Evento il 2026-05-15 alle 10") == "2026-05-15"


def test_slash_format_ddmmyyyy_returns_iso():
    assert parse_date_from_text("Si terra il 15/05/2026 a Roma") == "2026-05-15"


def test_dash_format_ddmmyyyy_returns_iso():
    assert parse_date_from_text("Si terra il 15-05-2026 a Roma") == "2026-05-15"


def test_italian_textual_format_returns_iso():
    assert parse_date_from_text("Convegno il 12 marzo 2026") == "2026-03-12"


def test_italian_textual_format_uppercase_month():
    assert parse_date_from_text("Convegno il 12 Marzo 2026") == "2026-03-12"


def test_reject_iso_pre_2024_cutoff():
    assert parse_date_from_text("Evento il 2023-12-31") is None


def test_reject_slash_pre_2024_cutoff():
    assert parse_date_from_text("Si terra il 31/12/2023") is None


def test_reject_italian_textual_pre_2024_cutoff():
    # With the explicit year "2023", the italian-with-year regex rejects it
    # (pre-cutoff) AND the noyear fallback must NOT reinterpret it as the
    # current year — a negative lookahead in RE_DATE_ITALIAN_NOYEAR enforces this.
    assert parse_date_from_text("Convegno il 15 giugno 2023") is None


def test_returns_none_on_empty_string():
    assert parse_date_from_text("") is None


def test_returns_none_when_no_date_present():
    assert parse_date_from_text("Nessuna data qui presente") is None


def test_returns_none_on_invalid_calendar_date():
    # 31 febbraio non esiste → cerca una data successiva nel testo, altrimenti None
    assert parse_date_from_text("Data fittizia 31/02/2026") is None
