#!/usr/bin/env python3
"""
Events Radar — Scheduled Scraper Entry Point

This script is invoked by the API server on demand or by the biweekly schedule.
It runs the full scraping cycle and emits a structured summary log.

Usage:
    python run_scraper.py            # normal scrape
    python run_scraper.py --cleanup  # remove noise events first, then scrape
    python run_scraper.py --dry-run  # LLM scrapers log events without DB writes

Exit code: 0 on success, 1 if any source produced an error.
"""

import argparse
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone

# Ensure 'scraper' resolves as a namespace package from the workspace root,
# not as the scraper.py module. When Python is invoked as
# "python scraper/run_scraper.py", it auto-prepends 'scraper/' to sys.path,
# which makes 'scraper.py' shadow the 'scraper/' package for top-level imports.
# Fix: prepend workspace root AND remove the script's directory from sys.path.
# This makes 'from scraper.scraper import ...' / 'from scraper.llm_scraper import ...'
# (used by sibling modules) resolve correctly.
_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path.insert(0, str(_WORKSPACE_ROOT))
if _SCRIPT_DIR in sys.path:
    sys.path.remove(_SCRIPT_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
log = logging.getLogger("run_scraper")

from scraper.scraper import run_scraper  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Events Radar scraper entry point")
    parser.add_argument("--cleanup", action="store_true", help="Remove noise events before scraping")
    parser.add_argument("--dry-run", action="store_true", help="LLM scrapers log events without DB writes")
    args = parser.parse_args()
    cleanup = args.cleanup
    dry_run = args.dry_run

    start = datetime.now(timezone.utc)
    log.info("=" * 60)
    log.info("  EVENTS RADAR — SCRAPER AVVIATO")
    if cleanup:
        log.info("  Modalità: scrape + cleanup rumore")
    if dry_run:
        log.info("  Modalità: DRY-RUN (no DB writes per scraper LLM)")
    log.info(f"  {start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info("=" * 60)

    try:
        stats = run_scraper(cleanup=cleanup, dry_run=dry_run)
    except Exception as exc:
        log.critical(f"Errore critico durante lo scraping: {exc}", exc_info=True)
        return 1

    end = datetime.now(timezone.utc)
    duration_s = (end - start).total_seconds()

    log.info("")
    log.info("=" * 60)
    log.info("  RIEPILOGO ESECUZIONE")
    log.info("=" * 60)
    log.info(f"  Inizio:             {start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info(f"  Fine:               {end.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info(f"  Durata:             {duration_s:.1f}s")
    log.info(f"  Fonti processate:   {stats['fonti_processed']}")
    log.info(f"  Nuovi eventi:       {stats['inserted']}")
    log.info(f"  Aggiornamenti:      {stats['updated']}")
    log.info(f"  Errori:             {stats['errors']}")
    if cleanup:
        log.info(f"  Rimossi (cleanup):  {stats.get('cleaned', 0)}")

    if stats["failed_fonti"]:
        log.info(f"  Fonti fallite:      {', '.join(stats['failed_fonti'])}")
    else:
        log.info("  Fonti fallite:      nessuna")

    log.info("=" * 60)

    if stats["errors"] > 0:
        log.warning(f"Completato con {stats['errors']} errore/i. Exit code 1.")
        return 1

    log.info("Completato senza errori. Exit code 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
