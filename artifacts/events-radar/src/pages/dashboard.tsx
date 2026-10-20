import { useState, useEffect, useMemo } from "react";
import {
  useListEvents,
  useListFonti,
  getListEventsQueryKey,
} from "@workspace/api-client-react";
import type {
  TipoEvento,
  Mercato,
  StatoOpportunita,
} from "@workspace/api-client-react";
import { format, parseISO } from "date-fns";
import EventMap from "@/components/EventMap";
import EventList from "@/components/EventList";
import SourcesPanel from "@/components/SourcesPanel";
import { LEGEND_ENTRIES } from "@/lib/eventColors";
import ErrorBoundary from "@/components/ErrorBoundary";
import { computeKpi, statoOf, useOpportunitaMap, withOpportunita } from "@/lib/opportunita";

const DEBOUNCE_DELAY_MS = 300;

function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    if (value === debouncedValue) return;
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}

export default function Dashboard() {
  const [luogo, setLuogo] = useState("");
  const [tipoEvento, setTipoEvento] = useState<TipoEvento | "">("");
  const [mercato, setMercato] = useState<Mercato | "">("");
  const [dataDa, setDataDa] = useState("");
  const [dataA, setDataA] = useState("");
  const [statoOpportunita, setStatoOpportunita] = useState<StatoOpportunita | "">("");
  const [includiPassati, setIncludiPassati] = useState(false);

  const debouncedLuogo = useDebounce(luogo, DEBOUNCE_DELAY_MS);

  const queryParams = {
    ...(debouncedLuogo ? { luogo: debouncedLuogo } : {}),
    ...(tipoEvento ? { tipo_evento: tipoEvento as TipoEvento } : {}),
    ...(mercato ? { mercato: mercato as Mercato } : {}),
    ...(dataDa ? { data_da: dataDa } : {}),
    ...(dataA ? { data_a: dataA } : {}),
    ...(includiPassati ? { includi_passati: true } : {}),
  };

  const filterKey = JSON.stringify({ ...queryParams, statoOpportunita });

  const { data: eventsData, isLoading: isLoadingEvents } = useListEvents(queryParams, {
    query: { enabled: true, queryKey: getListEventsQueryKey(queryParams) }
  });

  // Opportunity state lives in this browser, so the stato filter and its
  // counts are applied client-side on top of the server-filtered list.
  const opportunitaMap = useOpportunitaMap();
  const allEvents = useMemo(
    () => withOpportunita(eventsData?.events ?? [], opportunitaMap),
    [eventsData, opportunitaMap],
  );
  const visibleEvents = useMemo(
    () => (statoOpportunita ? allEvents.filter((e) => statoOf(e) === statoOpportunita) : allEvents),
    [allEvents, statoOpportunita],
  );
  const kpiData = computeKpi(visibleEvents);
  const statoCounts = computeKpi(allEvents);
  const isLoadingKpi = isLoadingEvents;

  const { data: fontiData } = useListFonti({
    query: { enabled: true, queryKey: ["/api/fonti"] }
  });

  const lastScrapeDate = fontiData?.fonti
    .map((f) => f.ultimoScrape)
    .filter(Boolean)
    .sort()
    .at(-1);

  const totalCount = statoCounts.totaleEventi;
  const nonContattatoCount = statoCounts.nonContattato;
  const contattatoCount = statoCounts.contattato;
  const rispostoCount = statoCounts.risposto;
  const nonRispostoCount = statoCounts.nonRisposto;

  return (
    <div className="layout-container">
      <header className="header">
        <div className="header-left">
          <h1 className="header-title heading">Events Radar</h1>
        </div>
        <div className="header-right">
          <span className="header-subtitle">Dashboard per il team BD</span>
        </div>
      </header>

      <main className="content">
        <section className="kpi-bar">
          <div className="kpi-card">
            <div className="kpi-label">Totale eventi</div>
            <div className="kpi-value">
              {isLoadingKpi ? <div className="loading-skeleton" style={{width: 60, height: 32}}></div> : kpiData.totaleEventi ?? 0}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Questo mese</div>
            <div className="kpi-value">
              {isLoadingKpi ? <div className="loading-skeleton" style={{width: 60, height: 32}}></div> : kpiData.questoMese ?? 0}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Italia</div>
            <div className="kpi-value">
              {isLoadingKpi ? <div className="loading-skeleton" style={{width: 60, height: 32}}></div> : kpiData.italia ?? 0}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Internazionale</div>
            <div className="kpi-value">
              {isLoadingKpi ? <div className="loading-skeleton" style={{width: 60, height: 32}}></div> : kpiData.internazionale ?? 0}
            </div>
          </div>
          <div className="kpi-card kpi-card--risposto">
            <div className="kpi-label">Risposto</div>
            <div className="kpi-value">
              {isLoadingKpi ? <div className="loading-skeleton" style={{width: 60, height: 32}}></div> : rispostoCount}
            </div>
          </div>
          <div className="kpi-card kpi-card--non-risposto">
            <div className="kpi-label">Non risposto</div>
            <div className="kpi-value">
              {isLoadingKpi ? <div className="loading-skeleton" style={{width: 60, height: 32}}></div> : nonRispostoCount}
            </div>
          </div>
        </section>

        <section className="filter-bar">
          <input
            type="text"
            placeholder="Città / Regione"
            className="filter-input"
            value={luogo}
            onChange={(e) => setLuogo(e.target.value)}
            aria-label="Filtra per città o regione"
          />
          <select
            className="filter-select"
            value={tipoEvento}
            onChange={(e) => setTipoEvento(e.target.value as TipoEvento | "")}
            aria-label="Filtra per tipo evento"
          >
            <option value="">Tutti i tipi</option>
            <option value="convegno">Convegno</option>
            <option value="corso_formativo">Corso Formativo</option>
            <option value="fiera_legaltech">Fiera Legaltech</option>
            <option value="congresso">Congresso</option>
            <option value="webinar">Webinar</option>
            <option value="altro">Altro</option>
          </select>
          <select
            className="filter-select"
            value={mercato}
            onChange={(e) => setMercato(e.target.value as Mercato | "")}
            aria-label="Filtra per mercato"
          >
            <option value="">Tutti i mercati</option>
            <option value="italia">Italia</option>
            <option value="internazionale">Internazionale</option>
          </select>
          <input
            type="date"
            className="filter-input"
            value={dataDa}
            onChange={(e) => setDataDa(e.target.value)}
            aria-label="Data inizio filtro"
          />
          <input
            type="date"
            className="filter-input"
            value={dataA}
            onChange={(e) => setDataA(e.target.value)}
            aria-label="Data fine filtro"
          />
          <label className="filter-toggle-label">
            <input
              type="checkbox"
              className="filter-toggle-checkbox"
              checked={includiPassati}
              onChange={(e) => setIncludiPassati(e.target.checked)}
              aria-label="Mostra eventi passati"
            />
            Mostra eventi passati
          </label>
          <div className="segmented-control">
            <button
              className={`segment-btn ${statoOpportunita === "" ? "active" : ""}`}
              onClick={() => setStatoOpportunita("")}
            >
              Tutti {!isLoadingKpi && <span className="segment-count">({totalCount})</span>}
            </button>
            <button
              className={`segment-btn ${statoOpportunita === "non_contattato" ? "active" : ""}`}
              onClick={() => setStatoOpportunita("non_contattato")}
            >
              Non contattato {!isLoadingKpi && <span className="segment-count">({nonContattatoCount})</span>}
            </button>
            <button
              className={`segment-btn ${statoOpportunita === "contattato" ? "active" : ""}`}
              onClick={() => setStatoOpportunita("contattato")}
            >
              Contattato {!isLoadingKpi && <span className="segment-count">({contattatoCount})</span>}
            </button>
            <button
              className={`segment-btn ${statoOpportunita === "risposto" ? "active" : ""}`}
              onClick={() => setStatoOpportunita("risposto")}
            >Risposto</button>
            <button
              className={`segment-btn ${statoOpportunita === "non_risposto" ? "active" : ""}`}
              onClick={() => setStatoOpportunita("non_risposto")}
            >Non risposto</button>
            <button
              className={`segment-btn ${statoOpportunita === "archiviato" ? "active" : ""}`}
              onClick={() => setStatoOpportunita("archiviato")}
            >Archiviato</button>
          </div>
        </section>

        <section className="main-area">
          <div className="map-container" style={{display: 'flex', flexDirection: 'column'}}>
            <div style={{flex: 1, minHeight: 0}}>
              <ErrorBoundary fallbackMessage="Errore nel caricamento della mappa." resetKey={filterKey}>
                <EventMap events={visibleEvents} />
              </ErrorBoundary>
            </div>
            <div className="map-legend">
              {LEGEND_ENTRIES.map(({ tipo, label, color }) => (
                <span key={tipo} className="map-legend-item">
                  <span className="map-legend-dot" style={{background: color}} />
                  {label}
                </span>
              ))}
            </div>
          </div>
          <div className="list-container">
            <ErrorBoundary fallbackMessage="Errore nel caricamento della lista eventi." resetKey={filterKey}>
              {isLoadingEvents ? (
                Array.from({length: 4}).map((_, i) => (
                  <div key={i} className="event-card">
                    <div className="loading-skeleton" style={{width: '40%', height: 20}}></div>
                    <div className="loading-skeleton" style={{width: '80%', height: 16}}></div>
                    <div className="loading-skeleton" style={{width: '60%', height: 14}}></div>
                  </div>
                ))
              ) : visibleEvents.length === 0 ? (
                <div style={{padding: '2rem', textAlign: 'center', color: 'var(--color-dark-gray)'}}>
                  Nessun evento trovato
                </div>
              ) : (
                <EventList events={visibleEvents} />
              )}
            </ErrorBoundary>
          </div>
        </section>

        <ErrorBoundary fallbackMessage="Errore nel caricamento delle fonti." resetKey={filterKey}>
          <SourcesPanel />
        </ErrorBoundary>
      </main>

      <footer className="footer">
        <div>Dati raccolti da fonti pubbliche a scopo di monitoraggio commerciale interno. Prototipo indipendente, costruito di mia iniziativa con sole fonti pubbliche durante una candidatura in una legaltech italiana. Non commissionato né approvato dall'azienda.</div>
        <div>
          Ultimo aggiornamento scraper:{" "}
          {lastScrapeDate
            ? format(parseISO(lastScrapeDate), 'dd/MM/yyyy HH:mm')
            : "—"}
        </div>
      </footer>
    </div>
  );
}
