"""Story 3.7 — Backfill source_event_uid (Python fallback).

Usa questo script se `pgcrypto` non e disponibile sul DB Replit
(lo script SQL `lib/db/backfill/3-7-backfill-source-event-uid.sql` fallisce
al CREATE EXTENSION pgcrypto).

Algoritmo identico a scraper.py::_make_source_event_uid:
    norm_title = _normalize_title(titolo)   # lower + strip + collapse whitespace
    payload    = f"{norm_title}|{data_inizio or ''}|{id_fonte}"
    uid        = sha256(payload).hexdigest()[:32]

Esecuzione:
    export DATABASE_URL=postgres://...
    python scraper/backfill_source_event_uid.py

ESEGUIRE PRIMA di `pnpm --filter @workspace/db run push`.
Dual-DB Replit: eseguire su DEV e PROD separatamente.
"""

import hashlib
import os
import re
import sys

import psycopg2


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").lower().strip())


def _make_source_event_uid(titolo, data_inizio, id_fonte) -> str:
    # Allineato a scraper.py::insert_evento: applica fallback "Senza titolo"
    # PRIMA della normalizzazione, cosi l'uid calcolato qui coincide con
    # quello calcolato dallo scraper a runtime (story 3.7 review fix C2).
    raw_title = titolo if titolo else "Senza titolo"
    norm_title = _normalize_title(raw_title)
    date_str = data_inizio if data_inizio is not None else ""
    payload = f"{norm_title}|{date_str}|{id_fonte or 0}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL non impostato", file=sys.stderr)
        return 1

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            # 1) Aggiungi colonna nullable se assente
            cur.execute(
                "ALTER TABLE evento ADD COLUMN IF NOT EXISTS source_event_uid text"
            )

            # 2) Fetch tutti i record senza UID
            cur.execute(
                "SELECT id, titolo, data_inizio, id_fonte FROM evento "
                "WHERE source_event_uid IS NULL"
            )
            rows = cur.fetchall()
            print(f"[backfill] Trovati {len(rows)} record da popolare")

            # 3) UPDATE batch
            updated = 0
            for evento_id, titolo, data_inizio, id_fonte in rows:
                uid = _make_source_event_uid(titolo, data_inizio, id_fonte)
                cur.execute(
                    "UPDATE evento SET source_event_uid = %s WHERE id = %s",
                    (uid, evento_id),
                )
                updated += 1
                if updated % 500 == 0:
                    print(f"[backfill] {updated}/{len(rows)} aggiornati")
            print(f"[backfill] UPDATE completati: {updated}")

            # 4) Verifica collisioni
            cur.execute(
                """
                SELECT source_event_uid, id_fonte, COUNT(*) AS dupes,
                       array_agg(id ORDER BY id) AS evento_ids
                FROM evento
                WHERE source_event_uid IS NOT NULL
                GROUP BY source_event_uid, id_fonte
                HAVING COUNT(*) > 1
                """
            )
            collisions = cur.fetchall()
            if collisions:
                print(
                    f"[backfill] ATTENZIONE: {len(collisions)} collisioni trovate.",
                    file=sys.stderr,
                )
                for uid, id_fonte, dupes, ids in collisions:
                    print(
                        f"  uid={uid} id_fonte={id_fonte} dupes={dupes} ids={ids}",
                        file=sys.stderr,
                    )
                print(
                    "[backfill] Risolvere manualmente le collisioni prima di continuare "
                    "(spostare opportunita su record vincitore, poi DELETE loser). "
                    "Vedi commenti in lib/db/backfill/3-7-backfill-source-event-uid.sql.",
                    file=sys.stderr,
                )
                conn.rollback()
                return 2

            # 5) Imposta NOT NULL
            cur.execute(
                "ALTER TABLE evento ALTER COLUMN source_event_uid SET NOT NULL"
            )

            # 6) Verifica finale
            cur.execute("SELECT COUNT(*) FROM evento WHERE source_event_uid IS NULL")
            null_count = cur.fetchone()[0]
            if null_count != 0:
                print(
                    f"[backfill] ERRORE: residuo {null_count} NULL — rollback",
                    file=sys.stderr,
                )
                conn.rollback()
                return 3

        conn.commit()
        print(
            "[backfill] OK — colonna popolata e NOT NULL. "
            "Ora eseguire: pnpm --filter @workspace/db run push"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
