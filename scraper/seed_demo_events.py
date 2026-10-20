#!/usr/bin/env python3
"""
Seed demo events into the database for Events Radar.
Run once to populate initial data for testing/demo.
"""

import os
import sys
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

DEMO_EVENTS = [
    # ISI Formazione - Corsi formativi
    {
        "titolo": "Corso di Formazione: Diritto di Famiglia e Minori — Tecniche processuali avanzate",
        "data_inizio": "2026-05-14",
        "data_fine": "2026-05-14",
        "luogo": "Milano",
        "lat": 45.4642, "lng": 9.1900,
        "tipo_evento": "corso_formativo",
        "organizzatore": "ISI Formazione",
        "crediti_formativi": 6,
        "url_sorgente": "https://www.isiformazione.it/ita/_V2.0_risultatiricerca.asp?TipoOrdine=Avvocati",
        "mercato": "italia",
        "fonte_nome": "ISI Formazione",
    },
    {
        "titolo": "Contrattualistica Internazionale: GDPR e Data Governance nelle PMI",
        "data_inizio": "2026-05-22",
        "data_fine": "2026-05-22",
        "luogo": "Roma",
        "lat": 41.9028, "lng": 12.4964,
        "tipo_evento": "corso_formativo",
        "organizzatore": "ISI Formazione",
        "crediti_formativi": 6,
        "url_sorgente": "https://www.isiformazione.it/ita/_V2.0_risultatiricerca.asp?TipoOrdine=Avvocati",
        "mercato": "italia",
        "fonte_nome": "ISI Formazione",
    },
    {
        "titolo": "Diritto del Lavoro 2026: Riforma dei contratti e giurisprudenza recente",
        "data_inizio": "2026-06-10",
        "data_fine": "2026-06-11",
        "luogo": "Torino",
        "lat": 45.0703, "lng": 7.6869,
        "tipo_evento": "corso_formativo",
        "organizzatore": "ISI Formazione",
        "crediti_formativi": 12,
        "url_sorgente": "https://www.isiformazione.it/ita/_V2.0_risultatiricerca.asp?TipoOrdine=Avvocati",
        "mercato": "italia",
        "fonte_nome": "ISI Formazione",
    },
    # CNF
    {
        "titolo": "Congresso Nazionale Forense 2026 — L'avvocatura nel mondo digitale",
        "data_inizio": "2026-10-15",
        "data_fine": "2026-10-17",
        "luogo": "Napoli",
        "lat": 40.8518, "lng": 14.2681,
        "tipo_evento": "congresso",
        "organizzatore": "Consiglio Nazionale Forense",
        "crediti_formativi": 18,
        "url_sorgente": "https://www.consiglionazionaleforense.it/web/cnf-news/calendario-eventi",
        "mercato": "italia",
        "fonte_nome": "CNF Calendario",
    },
    {
        "titolo": "Convegno CNF: Intelligenza Artificiale e professione forense",
        "data_inizio": "2026-06-25",
        "data_fine": "2026-06-25",
        "luogo": "Roma",
        "lat": 41.9028, "lng": 12.4964,
        "tipo_evento": "convegno",
        "organizzatore": "Consiglio Nazionale Forense",
        "crediti_formativi": 6,
        "url_sorgente": "https://www.consiglionazionaleforense.it/web/cnf-news/calendario-eventi",
        "mercato": "italia",
        "fonte_nome": "CNF Calendario",
    },
    # Legal Tech Forum Italia
    {
        "titolo": "Legal Tech Forum Italia 2026 — Trasformazione digitale degli studi legali",
        "data_inizio": "2026-09-18",
        "data_fine": "2026-09-19",
        "luogo": "Milano",
        "lat": 45.4642, "lng": 9.1900,
        "tipo_evento": "fiera_legaltech",
        "organizzatore": "Legal Tech Forum",
        "crediti_formativi": None,
        "url_sorgente": "https://forum.legaltechitaly.com/",
        "mercato": "italia",
        "fonte_nome": "Legal Tech Forum",
    },
    # GLTH Milano
    {
        "titolo": "GLTH Milano: AI nel contratto — rischi e opportunità per gli studi legali",
        "data_inizio": "2026-05-28",
        "data_fine": "2026-05-28",
        "luogo": "Milano",
        "lat": 45.4642, "lng": 9.1900,
        "tipo_evento": "fiera_legaltech",
        "organizzatore": "GLTH Milano",
        "crediti_formativi": None,
        "url_sorgente": "https://www.hublegaltech.com/agenda",
        "mercato": "italia",
        "fonte_nome": "GLTH Milano",
    },
    {
        "titolo": "GLTH Evening: Contract Intelligence con LLM — demo live",
        "data_inizio": "2026-06-18",
        "data_fine": "2026-06-18",
        "luogo": "Milano",
        "lat": 45.4642, "lng": 9.1900,
        "tipo_evento": "fiera_legaltech",
        "organizzatore": "GLTH Milano",
        "crediti_formativi": None,
        "url_sorgente": "https://www.hublegaltech.com/agenda",
        "mercato": "italia",
        "fonte_nome": "GLTH Milano",
    },
    # LegalTechTalk (internazionale)
    {
        "titolo": "LegalTechTalk Summit Europe 2026 — Disrupting Legal Services",
        "data_inizio": "2026-11-05",
        "data_fine": "2026-11-06",
        "luogo": "Amsterdam",
        "lat": 52.3676, "lng": 4.9041,
        "tipo_evento": "fiera_legaltech",
        "organizzatore": "LegalTechTalk",
        "crediti_formativi": None,
        "url_sorgente": "https://www.legaltech-talk.com/",
        "mercato": "internazionale",
        "fonte_nome": "LegalTechTalk",
    },
    # Lexpo
    {
        "titolo": "Lexpo 2026 — International Legal Innovation Exhibition",
        "data_inizio": "2026-09-10",
        "data_fine": "2026-09-12",
        "luogo": "Amsterdam",
        "lat": 52.3676, "lng": 4.9041,
        "tipo_evento": "fiera_legaltech",
        "organizzatore": "Lexpo",
        "crediti_formativi": None,
        "url_sorgente": "https://lexpo.com/",
        "mercato": "internazionale",
        "fonte_nome": "Lexpo",
    },
    # Camera Civile di Rimini
    {
        "titolo": "Convegno: Il nuovo processo civile telematico — aggiornamenti 2026",
        "data_inizio": "2026-05-09",
        "data_fine": "2026-05-09",
        "luogo": "Rimini",
        "lat": 44.0678, "lng": 12.5695,
        "tipo_evento": "convegno",
        "organizzatore": "Camera Civile di Rimini",
        "crediti_formativi": 6,
        "url_sorgente": "https://www.cameracivilerimini.it/formazione/",
        "mercato": "italia",
        "fonte_nome": "Camera Civile di Rimini",
    },
    {
        "titolo": "Corso pratico: Mediazione civile e commerciale — aggiornamento obbligatorio",
        "data_inizio": "2026-06-06",
        "data_fine": "2026-06-06",
        "luogo": "Rimini",
        "lat": 44.0678, "lng": 12.5695,
        "tipo_evento": "corso_formativo",
        "organizzatore": "Camera Civile di Rimini",
        "crediti_formativi": 6,
        "url_sorgente": "https://www.cameracivilerimini.it/formazione/",
        "mercato": "italia",
        "fonte_nome": "Camera Civile di Rimini",
    },
    # AIGA
    {
        "titolo": "AIGA Forum 2026 — Giovani avvocati e innovazione: scenari futuri",
        "data_inizio": "2026-07-04",
        "data_fine": "2026-07-05",
        "luogo": "Firenze",
        "lat": 43.7696, "lng": 11.2558,
        "tipo_evento": "congresso",
        "organizzatore": "AIGA",
        "crediti_formativi": 12,
        "url_sorgente": "https://www.aiga.it/",
        "mercato": "italia",
        "fonte_nome": "AIGA",
    },
    # ANF
    {
        "titolo": "ANF Convegno Nazionale: Deontologia e AI — linee guida per l'avvocatura",
        "data_inizio": "2026-09-25",
        "data_fine": "2026-09-26",
        "luogo": "Bologna",
        "lat": 44.4949, "lng": 11.3426,
        "tipo_evento": "convegno",
        "organizzatore": "ANF",
        "crediti_formativi": 12,
        "url_sorgente": "https://www.associazionenazionaleforense.it/",
        "mercato": "italia",
        "fonte_nome": "ANF",
    },
    # Date da confermare
    {
        "titolo": "Webinar: Startup Legali — dalla compliance all'exit strategy",
        "data_inizio": None,
        "data_fine": None,
        "luogo": "Online",
        "lat": None, "lng": None,
        "tipo_evento": "webinar",
        "organizzatore": "GLTH Milano",
        "crediti_formativi": None,
        "url_sorgente": "https://www.hublegaltech.com/agenda",
        "mercato": "italia",
        "fonte_nome": "GLTH Milano",
    },
    {
        "titolo": "Corso: Privacy by Design nelle piattaforme SaaS legali — TBD 2026",
        "data_inizio": None,
        "data_fine": None,
        "luogo": "Online",
        "lat": None, "lng": None,
        "tipo_evento": "corso_formativo",
        "organizzatore": "LegalTechTalk",
        "crediti_formativi": None,
        "url_sorgente": "https://www.legaltech-talk.com/",
        "mercato": "internazionale",
        "fonte_nome": "LegalTechTalk",
    },
]


def get_fonte_id(cur, nome: str):
    cur.execute("SELECT id FROM fonte WHERE nome = %s", (nome,))
    row = cur.fetchone()
    return row[0] if row else None


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Check if already seeded
    cur.execute("SELECT COUNT(*) FROM evento")
    count = cur.fetchone()[0]
    if count > 0:
        print(f"Events already present ({count}), skipping demo seed.")
        conn.close()
        return

    inserted = 0
    for ev in DEMO_EVENTS:
        fonte_nome = ev.pop("fonte_nome")
        fonte_id = get_fonte_id(cur, fonte_nome)
        if fonte_id is None:
            print(f"WARNING: Fonte '{fonte_nome}' not found, skipping event: {ev['titolo']}")
            continue

        try:
            cur.execute(
                """
                INSERT INTO evento (
                    titolo, data_inizio, data_fine, luogo, lat, lng,
                    tipo_evento, organizzatore, crediti_formativi,
                    url_sorgente, id_fonte, mercato,
                    data_inserimento, data_ultimo_aggiornamento
                ) VALUES (
                    %(titolo)s, %(data_inizio)s, %(data_fine)s, %(luogo)s, %(lat)s, %(lng)s,
                    %(tipo_evento)s, %(organizzatore)s, %(crediti_formativi)s,
                    %(url_sorgente)s, %(id_fonte)s, %(mercato)s,
                    NOW(), NOW()
                )
                RETURNING id
                """,
                {**ev, "id_fonte": fonte_id},
            )
            evento_id = cur.fetchone()[0]

            # Create opportunita
            cur.execute(
                """
                INSERT INTO opportunita (id_evento, stato, data_ultimo_aggiornamento)
                VALUES (%s, 'non_contattato', NOW())
                """,
                (evento_id,)
            )
            inserted += 1
            print(f"  [OK] {ev['titolo'][:60]}")

        except Exception as e:
            print(f"  [ERR] {ev.get('titolo', '?')[:60]}: {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDemo seed complete: {inserted} events inserted.")


if __name__ == "__main__":
    main()
