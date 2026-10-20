"""Unit tests for scraper.scraper.insert_evento (AC #3).

Uses a fake psycopg2-like connection/cursor to inspect the SQL emitted by
`insert_evento` and verify dedup behaviour via `ON CONFLICT (source_event_uid,
id_fonte) DO UPDATE`. No real Postgres needed.

The goal is to verify, at the unit-test level, that:
 1) A single INSERT ... ON CONFLICT statement is emitted (idempotent upsert).
 2) Inserting the same event twice does NOT emit two different INSERTs with
    diverging UIDs — the `source_event_uid` is stable across calls.
 3) The opportunita row is also inserted with `ON CONFLICT DO NOTHING`.
"""

from __future__ import annotations

from typing import Any, Optional

from scraper.scraper import insert_evento


class FakeCursor:
    def __init__(self, inserted: bool = True, existing_luogo: Optional[str] = None):
        # When True, simulate a fresh INSERT (xmax = 0 → inserted=True).
        self._inserted = inserted
        self._existing_luogo = existing_luogo
        self.executed: list[tuple[str, Any]] = []
        self._fetch_queue: list[Any] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))
        # Queue the fetch result based on which statement we just executed.
        if sql.strip().startswith("SELECT id, luogo FROM evento"):
            self._fetch_queue.append(
                None if self._existing_luogo is None else (1, self._existing_luogo)
            )
        elif sql.strip().startswith("INSERT INTO evento"):
            self._fetch_queue.append((1, self._inserted))

    def fetchone(self) -> Any:
        return self._fetch_queue.pop(0) if self._fetch_queue else None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1


def _sample_evento() -> dict[str, Any]:
    return {
        "titolo": "Convegno Test sul LegalTech 2026",
        "data_inizio": "2026-05-15",
        "data_fine": None,
        "luogo": "Roma",
        "lat": None,
        "lng": None,
        "tipo_evento": "convegno",
        "organizzatore": "Org Test",
        "crediti_formativi": None,
        "url_sorgente": "https://example.org/ev1",
        "mercato": "italia",
    }


def _find_stmt(cursor: FakeCursor, needle: str) -> Optional[tuple[str, Any]]:
    for sql, params in cursor.executed:
        if needle in sql:
            return sql, params
    return None


def test_emits_on_conflict_upsert_on_evento():
    cursor = FakeCursor(inserted=True)
    conn = FakeConn(cursor)

    result = insert_evento(conn, _sample_evento(), fonte_id=1)

    assert result == 1  # positive id → new event inserted
    stmt = _find_stmt(cursor, "INSERT INTO evento")
    assert stmt is not None, "expected an INSERT INTO evento statement"
    sql, params = stmt
    assert "ON CONFLICT (source_event_uid, id_fonte) DO UPDATE" in sql
    assert "source_event_uid" in params
    assert params["id_fonte"] == 1
    assert conn.commits == 1


def test_emits_on_conflict_do_nothing_on_opportunita():
    cursor = FakeCursor(inserted=True)
    conn = FakeConn(cursor)
    insert_evento(conn, _sample_evento(), fonte_id=2)

    stmt = _find_stmt(cursor, "INSERT INTO opportunita")
    assert stmt is not None, "expected an INSERT INTO opportunita statement"
    sql, _ = stmt
    assert "ON CONFLICT DO NOTHING" in sql


def test_stable_source_event_uid_across_calls():
    """Same (titolo, data_inizio, fonte_id) produces the same source_event_uid —
    this is what makes the upsert idempotent and prevents duplicate INSERTs.
    """
    evento = _sample_evento()
    uids: list[str] = []
    for _ in range(2):
        cursor = FakeCursor(inserted=False, existing_luogo="Roma")
        conn = FakeConn(cursor)
        insert_evento(conn, evento, fonte_id=7)
        stmt = _find_stmt(cursor, "INSERT INTO evento")
        assert stmt is not None
        _, params = stmt
        uids.append(params["source_event_uid"])

    assert uids[0] == uids[1], "source_event_uid must be stable for identical events"


def test_existing_event_without_luogo_change_returns_zero():
    # inserted=False → existing row, luogo unchanged → return_value == 0
    cursor = FakeCursor(inserted=False, existing_luogo="Roma")
    conn = FakeConn(cursor)
    result = insert_evento(conn, _sample_evento(), fonte_id=1)
    assert result == 0
