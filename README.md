# Events Radar

Prototipo non richiesto, costruito di mia iniziativa durante una candidatura in una legaltech italiana. È pensato come strumento interno per il team commerciale (SDR/BDR). Non è affiliato all'azienda né approvato da lei.

**Live:** https://legal-events-radar.vercel.app

## Cos'è

Events Radar è un prototipo di dashboard che aggrega e visualizza eventi, convegni, corsi di formazione e opportunità di partnership nel settore legale italiano e internazionale. Raccoglie dati da fonti pubbliche tramite scraping automatizzato e li presenta in un'interfaccia filtrabile per territorio, tipo di evento, periodo e mercato.

## A cosa serve

Dà al team commerciale una vista centralizzata delle opportunità di presenza nel settore legale: dove ci sono eventi rilevanti, quali enti organizzano formazione, dove investire tempo e risorse per portare l'azienda davanti a potenziali clienti e partner.

## Cosa include il prototipo

- Scraper Python che raccoglie eventi da un set limitato di fonti (ISI Formazione, CNF, AIGA, ANF, Legal Tech Forum, GLTH Milano, Camera Civile di Rimini, eventi legaltech internazionali)
- Dati in file JSON versionati nel repo (eventi con coordinate e fonti), nessun database
- Dashboard web con vista lista, vista mappa (Leaflet.js), KPI bar e filtri
- Gestione stato opportunità per ogni evento (non contattato → contattato → risposto / non risposto → archiviato), salvata nel browser (localStorage): ogni utente vede solo le proprie

## Cosa non include (semplificazioni dichiarate)

- Non copre tutti i 164 Ordini degli Avvocati. L'architettura è predisposta per scalare
- Nessuna integrazione CRM
- Nessun sistema di notifiche/alert automatici
- Nessuna deduplicazione automatica degli eventi tra fonti diverse
- I mercati esteri di riferimento (Spagna, Francia, Germania) non sono coperti con fonti locali. Sono inclusi solo eventi legaltech europei
- I titoli degli eventi internazionali restano nella lingua originale della fonte

## Stack tecnico

- **Scraper**: Python 3.11 (`requests` + `BeautifulSoup`, `Playwright` dove è necessario eseguire JavaScript), geocoding via Nominatim/OpenStreetMap
- **Dati**: `artifacts/api-server/src/data/events.json` e `fonti.json`, letti in memoria dall'API
- **Backend API**: Express 5 + Zod per la validazione, sola lettura (pacchetto `@workspace/api-server`)
- **Frontend**: React 18 + Vite + TanStack React Query + Leaflet.js + shadcn/Radix UI (pacchetto `@workspace/events-radar`)
- **Mappa**: Leaflet.js con tiles CartoDB Light
- **Monorepo**: pnpm workspaces (`artifacts/*`, `lib/*`, `lib/integrations/*`, `scripts`) con TypeScript composite projects
- **Codegen API**: OpenAPI 3.1 spec + Orval (genera client React Query in `lib/api-client-react` e schemi Zod in `lib/api-zod`)
- **Deploy**: Vercel (SPA statica + API Express come funzione serverless)

## Come avviare

Prerequisiti:

- Node.js 24 + pnpm 10.13.x
- Python 3.11 (solo per eseguire scraper e relativi test)

Comandi (eseguiti dalla root del monorepo — sono gli stessi utilizzati in CI):

```bash
# 1. Installa le dipendenze del monorepo
pnpm install --frozen-lockfile

# 2. Installa le dipendenze Python dello scraper (necessarie per test:scraper e run_scraper.py)
python -m pip install --upgrade pip
python -m pip install pytest psycopg2-binary requests beautifulsoup4 lxml

# 3. Type check (tsc --build su tutti i progetti composite)
pnpm run typecheck

# 4. Build completa (typecheck + build ricorsivo di ogni package)
pnpm run build

# 5. Suite test TypeScript (vitest backend + frontend)
pnpm run test

# 6. Suite test scraper (pytest, esclude i test marcati llm)
pnpm run test:scraper
```

Comandi di sviluppo (uno per terminale):

```bash
# Backend API (Express 5)
pnpm --filter @workspace/api-server run dev

# Frontend dashboard (React + Vite)
pnpm --filter @workspace/events-radar run dev
```

## Deploy su Vercel

`pnpm run vercel-build` compila la dashboard e impacchetta l'API Express in un'unica funzione, scrivendo direttamente in `.vercel/output` (Build Output API). `vercel.json` è già configurato: basta importare il repo su Vercel. Non servono variabili d'ambiente né database.

Gli eventi mostrati sono quelli in `artifacts/api-server/src/data/events.json` (eventi reali, con `lat`/`lng` per la mappa; `null` per quelli online). Per aggiornarli si modifica il file e si fa push: Vercel rideploya da solo. Lo stato delle opportunità e le note restano nel browser di chi le inserisce.

Lo scraper Python (`scraper/`) scrive ancora su Postgres e non è collegato al deploy: va adattato per produrre `events.json`.

## Struttura del monorepo

```text
events-radar/
├── artifacts/                  # Applicazioni deployabili
│   ├── api-server/             # @workspace/api-server — Express 5 API server
│   ├── events-radar/           # @workspace/events-radar — dashboard React + Vite
│   └── mockup-sandbox/         # sandbox di mockup UI
├── lib/                        # Pacchetti condivisi
│   ├── db/                     # @workspace/db — schema Drizzle usato solo dallo scraper (da rimuovere)
│   ├── api-spec/               # @workspace/api-spec — OpenAPI 3.1 spec + Orval codegen
│   ├── api-zod/                # @workspace/api-zod — schemi Zod generati
│   ├── api-client-react/       # @workspace/api-client-react — hook React Query generati
│   └── integrations/           # Workspace riservato per integrazioni esterne (attualmente vuoto)
├── scripts/                    # @workspace/scripts — utility TypeScript
├── scraper/                    # Scraper Python 3.11 standalone (pyproject.toml)
├── pnpm-workspace.yaml         # Dichiarazione workspace pnpm
├── tsconfig.base.json          # Config TS condivisa (composite)
├── tsconfig.json               # Root TS project references
└── package.json                # Root con script hoisted
```
