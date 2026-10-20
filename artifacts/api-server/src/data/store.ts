import eventsJson from "./events.json" with { type: "json" };
import fontiJson from "./fonti.json" with { type: "json" };

export type TipoEvento = "convegno" | "corso_formativo" | "fiera_legaltech" | "congresso" | "webinar" | "altro";
export type Mercato = "italia" | "internazionale";
export type TipoFonte = "aggregatore" | "ordine" | "associazione" | "legaltech" | "ente_formativo";

export interface Evento {
  id: number;
  titolo: string;
  dataInizio: string | null;
  dataFine: string | null;
  luogo: string | null;
  lat: number | null;
  lng: number | null;
  tipoEvento: TipoEvento;
  organizzatore: string | null;
  creditiFormativi: number | null;
  urlSorgente: string | null;
  idFonte: number | null;
  mercato: Mercato;
  dataInserimento: string;
  dataUltimoAggiornamento: string;
  // Opportunity state lives in the browser; the server never has one.
  opportunita: null;
  nomeFonte: string | null;
}

export interface Fonte {
  id: number;
  nome: string;
  urlBase: string;
  tipoFonte: TipoFonte;
  paese: string;
  statoScraper: "attivo";
  ultimoScrape: null;
  conteggioEventi: number;
}

export interface EventFilters {
  luogo?: string;
  tipo_evento?: string;
  mercato?: string;
  stato_opportunita?: string;
  data_da?: Date | string;
  data_a?: Date | string;
  includi_passati?: boolean;
}

const DATASET_DATE = "2026-10-14T00:00:00.000Z";

const fontiBase = fontiJson as Omit<Fonte, "statoScraper" | "ultimoScrape" | "conteggioEventi">[];
const fonteIdByName = new Map(fontiBase.map((f) => [f.nome, f.id]));

export const EVENTS: readonly Evento[] = eventsJson.map(({ fonte, ...e }) => {
  const idFonte = fonte === null ? null : fonteIdByName.get(fonte);
  if (idFonte === undefined) throw new Error(`events.json: unknown fonte "${fonte}" on event ${e.id}`);
  return {
    ...e,
    tipoEvento: e.tipoEvento as TipoEvento,
    mercato: e.mercato as Mercato,
    idFonte,
    nomeFonte: fonte,
    dataInserimento: DATASET_DATE,
    dataUltimoAggiornamento: DATASET_DATE,
    opportunita: null,
  };
});

export const FONTI: readonly Fonte[] = fontiBase
  .map((f) => ({
    ...f,
    statoScraper: "attivo" as const,
    ultimoScrape: null,
    conteggioEventi: EVENTS.filter((e) => e.idFonte === f.id).length,
  }))
  .sort((a, b) => a.nome.localeCompare(b.nome));

export function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

function toDateStr(d: Date | string | undefined): string | undefined {
  if (!d) return undefined;
  return typeof d === "string" ? d : d.toISOString().slice(0, 10);
}

export function filterEvents(params: EventFilters, today: string = todayUtc()): Evento[] {
  const luogo = params.luogo?.toLowerCase();
  const dataDa = toDateStr(params.data_da);
  const dataA = toDateStr(params.data_a);

  return EVENTS.filter((e) => {
    if (!params.includi_passati) {
      const end = e.dataFine ?? e.dataInizio;
      if (end === null || end < today) return false;
    }
    if (luogo && !e.luogo?.toLowerCase().includes(luogo)) return false;
    if (params.tipo_evento && e.tipoEvento !== params.tipo_evento) return false;
    if (params.mercato && e.mercato !== params.mercato) return false;
    if (dataDa && (e.dataInizio === null || e.dataInizio < dataDa)) return false;
    if (dataA && (e.dataInizio === null || e.dataInizio > dataA)) return false;
    // Every event is "non_contattato" server-side.
    if (params.stato_opportunita && params.stato_opportunita !== "non_contattato") return false;
    return true;
  }).sort((a, b) => {
    if (a.dataInizio === b.dataInizio) return a.id - b.id;
    if (a.dataInizio === null) return 1;
    if (b.dataInizio === null) return -1;
    return a.dataInizio < b.dataInizio ? -1 : 1;
  });
}

export function computeKpi(events: readonly Evento[], today: string = todayUtc()) {
  const month = today.slice(0, 7);
  return {
    totaleEventi: events.length,
    questoMese: events.filter((e) => e.dataInizio?.startsWith(month)).length,
    italia: events.filter((e) => e.mercato === "italia").length,
    internazionale: events.filter((e) => e.mercato === "internazionale").length,
    nonContattato: events.length,
    contattato: 0,
    risposto: 0,
    nonRisposto: 0,
  };
}
