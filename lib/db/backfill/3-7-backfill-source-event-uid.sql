-- Story 3.7: Backfill source_event_uid on existing evento records
-- =================================================================
-- ESEGUIRE PRIMA di `pnpm --filter @workspace/db run push`.
-- Altrimenti drizzle-kit push fallisce per NOT NULL violation sulla nuova colonna.
--
-- Algoritmo UID (stesso dello scraper Python):
--   raw_title  = CASE WHEN titolo IS NULL OR titolo = '' THEN 'Senza titolo' ELSE titolo END
--   norm_title = trim(lower(regexp_replace(raw_title, '\s+', ' ', 'g')))
--   payload    = norm_title || '|' || coalesce(data_inizio, '') || '|' || id_fonte::text
--   uid        = substring(encode(digest(payload, 'sha256'), 'hex') from 1 for 32)
-- NOTE: il fallback "Senza titolo" e coerente con insert_evento() che persiste
-- questo valore quando titolo e None/empty. Senza allineamento, la dedup
-- cross-run fallirebbe per eventi con titolo vuoto (story 3.7 review fix C2).
--
-- NOTA: richiede extension pgcrypto. Se non disponibile usare lo script Python
-- alternativo in scraper/backfill_source_event_uid.py.
--
-- Dual-DB Replit: eseguire su DEV e PROD separatamente.
-- =================================================================

BEGIN;

-- 1) Abilita pgcrypto (idempotente)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 2) Aggiungi colonna nullable (temporaneamente)
ALTER TABLE evento ADD COLUMN IF NOT EXISTS source_event_uid text;

-- 3) Popola UID per tutti i record esistenti
UPDATE evento
SET source_event_uid = substring(
    encode(
        digest(
            trim(lower(regexp_replace(
                CASE WHEN titolo IS NULL OR titolo = '' THEN 'Senza titolo' ELSE titolo END,
                '\s+', ' ', 'g'
            ))) || '|' ||
            COALESCE(data_inizio, '') || '|' ||
            COALESCE(id_fonte, 0)::text,
            'sha256'
        ),
        'hex'
    )
    from 1 for 32
)
WHERE source_event_uid IS NULL;

-- 4) Verifica collisioni (stessa uid + stessa fonte): dovrebbe essere 0 righe
-- Se > 0, DEDUPLICARE prima di procedere (vedi step 5)
SELECT source_event_uid, id_fonte, COUNT(*) AS dupes, array_agg(id ORDER BY id) AS evento_ids
FROM evento
WHERE source_event_uid IS NOT NULL
GROUP BY source_event_uid, id_fonte
HAVING COUNT(*) > 1;

-- 5) Deduplica collisioni: tieni il record con id piu basso, sposta opportunita sul vincitore,
--    cancella i duplicati. Decommenta se step 4 trova collisioni.
--
-- -- Sposta opportunita dai duplicati al record vincitore (id piu basso)
-- UPDATE opportunita o
-- SET id_evento = winners.min_id
-- FROM (
--     SELECT source_event_uid, id_fonte, MIN(id) AS min_id
--     FROM evento
--     WHERE source_event_uid IS NOT NULL
--     GROUP BY source_event_uid, id_fonte
--     HAVING COUNT(*) > 1
-- ) winners
-- JOIN evento losers
--     ON losers.source_event_uid = winners.source_event_uid
--    AND losers.id_fonte = winners.id_fonte
--    AND losers.id <> winners.min_id
-- WHERE o.id_evento = losers.id;
--
-- -- Elimina le opportunita duplicate eventualmente rimaste (ON CONFLICT)
-- DELETE FROM opportunita o1
-- USING opportunita o2
-- WHERE o1.id_evento = o2.id_evento AND o1.id > o2.id;
--
-- -- Elimina gli eventi duplicati (loser)
-- DELETE FROM evento losers
-- USING (
--     SELECT source_event_uid, id_fonte, MIN(id) AS min_id
--     FROM evento
--     WHERE source_event_uid IS NOT NULL
--     GROUP BY source_event_uid, id_fonte
--     HAVING COUNT(*) > 1
-- ) winners
-- WHERE losers.source_event_uid = winners.source_event_uid
--   AND losers.id_fonte = winners.id_fonte
--   AND losers.id <> winners.min_id;

-- 6) Imposta NOT NULL
ALTER TABLE evento ALTER COLUMN source_event_uid SET NOT NULL;

-- 7) Verifica finale: nessun NULL residuo
SELECT COUNT(*) AS null_count FROM evento WHERE source_event_uid IS NULL;
-- Attesi: 0

COMMIT;

-- Dopo questo script, lanciare:
--   pnpm --filter @workspace/db run push
-- Il push aggiungera il vincolo UNIQUE composito (source_event_uid, id_fonte).
