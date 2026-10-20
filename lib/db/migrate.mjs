#!/usr/bin/env node
/**
 * Idempotent pre-build migration runner.
 *
 * Applies migrations that drizzle-kit push cannot execute non-interactively
 * (e.g. backfilling NOT NULL columns on populated tables). Each step uses
 * IF NOT EXISTS / conditional DO $$ guards so the script is safe to re-run.
 *
 * Run order in build:prod:
 *   1. node migrate.mjs       — data-level changes (backfill + NOT NULL + UNIQUE)
 *   2. drizzle-kit push       — applies any remaining schema-level changes
 *   3. node build.mjs         — compiles the server bundle
 *
 * UNIQUE constraint column order note (drizzle-kit 0.31.9):
 * drizzle-kit introspects unique constraints via information_schema.constraint_column_usage
 * joined to information_schema.columns WITHOUT ORDER BY. PostgreSQL returns the columns
 * in table ordinal_position order (id_fonte=12, source_event_uid=17), regardless of the
 * physical index column order. The schema and this script both use (id_fonte, source_event_uid)
 * order so the drizzle string comparison (`squashUnique`) finds an exact match and reports
 * "[i] No changes detected" — no interactive prompt is shown.
 *
 * Add future migrations as new async functions below, called from main().
 */
import { execFileSync } from "child_process";
import { fileURLToPath } from "url";
import { dirname, resolve } from "path";
import pg from "pg";

// Resolve paths relative to this file regardless of the caller's CWD.
const __dirname = dirname(fileURLToPath(import.meta.url));
const PYTHON_BACKFILL_SCRIPT = resolve(__dirname, "../../scraper/backfill_source_event_uid.py");

const { Pool } = pg;

if (!process.env.DATABASE_URL) {
  console.error("[migrate] ERROR: DATABASE_URL is not set");
  process.exit(1);
}

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

async function query(sql, params = []) {
  return pool.query(sql, params);
}

async function step(label, sql) {
  await query(sql);
  console.log(`[migrate] ✓  ${label}`);
}

// ── Story 3.7 — robust event dedup ────────────────────────────────────────────
// Adds source_event_uid text NOT NULL + UNIQUE(source_event_uid, id_fonte)
// to the evento table and backfills all existing rows.
//
// Two-path backfill strategy:
//   Primary: pgcrypto digest() — pure-SQL, runs in the same transaction.
//   Fallback: scraper/backfill_source_event_uid.py — used when the DB user
//             lacks CREATE EXTENSION privileges.
//
// An explicit duplicate check runs before setting NOT NULL/UNIQUE so that
// any hash collision (theoretically possible, practically impossible with 32
// hex chars of SHA-256) is caught and reported before altering constraints.

async function migrateSourceEventUid() {
  // Skip entirely if the column is already NOT NULL — migration already done.
  const { rows: colRows } = await query(`
    SELECT is_nullable FROM information_schema.columns
    WHERE table_name = 'evento' AND column_name = 'source_event_uid'
  `);

  const alreadyNotNull =
    colRows.length > 0 && colRows[0].is_nullable === "NO";

  if (alreadyNotNull) {
    console.log("[migrate] ✓  source_event_uid already NOT NULL — skipping story 3.7 column/backfill");
  } else {
    console.log("[migrate] Running story 3.7 migration (source_event_uid) …");

    // Step 1 — add column as nullable (safe if it already exists).
    await step(
      "evento.source_event_uid nullable column",
      "ALTER TABLE evento ADD COLUMN IF NOT EXISTS source_event_uid text;"
    );

    // Step 2 — backfill: pgcrypto (primary) or Python script (fallback).
    let pgcryptoOk = false;
    try {
      await query("CREATE EXTENSION IF NOT EXISTS pgcrypto;");
      pgcryptoOk = true;
      console.log("[migrate] ✓  pgcrypto extension");
    } catch (err) {
      console.warn(
        `[migrate] ⚠  pgcrypto unavailable (${err.message}) — switching to Python fallback`
      );
    }

    if (pgcryptoOk) {
      await step(
        "backfill source_event_uid via pgcrypto",
        `UPDATE evento
         SET source_event_uid = substring(
           encode(
             digest(
               trim(lower(regexp_replace(
                 CASE WHEN titolo IS NULL OR titolo = '' THEN 'Senza titolo' ELSE titolo END,
                 '\\s+', ' ', 'g'
               ))) || '|' ||
               COALESCE(data_inizio, '') || '|' ||
               COALESCE(id_fonte, 0)::text,
               'sha256'
             ),
             'hex'
           )
           from 1 for 32
         )
         WHERE source_event_uid IS NULL;`
      );
    } else {
      // Python fallback: adds column, backfills, checks collisions, sets NOT NULL.
      console.log("[migrate] Running Python backfill script …");
      try {
        execFileSync("python3", [PYTHON_BACKFILL_SCRIPT], {
          env: { ...process.env },
          stdio: "inherit",
        });
        console.log("[migrate] ✓  Python backfill complete");
        // Python script already sets NOT NULL — jump to UNIQUE constraint.
        await ensureUniqueConstraint();
        return;
      } catch (err) {
        console.error("[migrate] FATAL: Python fallback failed:", err.message);
        throw err;
      }
    }

    // Step 3 — collision check: every (uid, id_fonte) pair must be unique.
    const { rows: collisions } = await query(`
      SELECT source_event_uid, id_fonte, COUNT(*) AS dupes,
             array_agg(id ORDER BY id) AS ids
      FROM evento
      GROUP BY source_event_uid, id_fonte
      HAVING COUNT(*) > 1;
    `);

    if (collisions.length > 0) {
      console.error(
        `[migrate] FATAL: ${collisions.length} UID collision(s) — resolve manually before re-running.\n` +
          collisions
            .map(
              (r) =>
                `  uid=${r.source_event_uid} id_fonte=${r.id_fonte} ids=${r.ids}`
            )
            .join("\n")
      );
      process.exit(2);
    }
    console.log("[migrate] ✓  0 UID collisions");

    // Step 4 — set NOT NULL (every row is now populated, 0 collisions confirmed).
    await step(
      "evento.source_event_uid SET NOT NULL",
      "ALTER TABLE evento ALTER COLUMN source_event_uid SET NOT NULL;"
    );
  }

  // Step 5 — UNIQUE constraint (idempotent: skipped if already present).
  await ensureUniqueConstraint();
}

async function ensureUniqueConstraint() {
  // Column order (id_fonte, source_event_uid) matches information_schema ordinal_position
  // ordering (id_fonte=12, source_event_uid=17), ensuring drizzle-kit's squashUnique
  // comparison produces an exact match with the schema definition.
  await step(
    "evento UNIQUE(source_event_uid, id_fonte)",
    `DO $$
     BEGIN
       IF NOT EXISTS (
         SELECT 1 FROM pg_constraint
         WHERE conrelid = 'evento'::regclass
           AND conname = 'evento_source_event_uid_id_fonte_key'
       ) THEN
         ALTER TABLE evento
           ADD CONSTRAINT evento_source_event_uid_id_fonte_key
           UNIQUE (id_fonte, source_event_uid);
       END IF;
     END $$;`
  );
}

// ── main ──────────────────────────────────────────────────────────────────────

async function main() {
  console.log("[migrate] Starting pre-build migrations …");

  await migrateSourceEventUid();

  console.log("[migrate] Pre-build migrations complete.");
  await pool.end();
}

main().catch((err) => {
  console.error("[migrate] FATAL:", err.message);
  pool.end();
  process.exit(1);
});
