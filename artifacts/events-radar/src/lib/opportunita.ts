import { useSyncExternalStore } from "react";
import { format } from "date-fns";
import type { EventWithOpportunita, StatoOpportunita } from "@workspace/api-client-react";

// Opportunity state is per-browser: there is no backend storage for it.
export const STORAGE_KEY = "events-radar:opportunita:v1";

interface StoredOpportunita {
  stato: StatoOpportunita;
  note: string | null;
  dataUltimoAggiornamento: string;
}

type OpportunitaMap = Record<string, StoredOpportunita>;

function read(): OpportunitaMap {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as OpportunitaMap) : {};
  } catch {
    return {};
  }
}

let snapshot: OpportunitaMap = read();
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === STORAGE_KEY) {
      snapshot = read();
      emit();
    }
  });
}

export function saveOpportunita(idEvento: number, stato: StatoOpportunita, note: string): void {
  snapshot = {
    ...snapshot,
    [idEvento]: { stato, note: note || null, dataUltimoAggiornamento: new Date().toISOString() },
  };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
  } catch {
    // Storage unavailable (private mode, quota): state still lives for this session.
  }
  emit();
}

export function resetOpportunitaForTests(): void {
  snapshot = read();
  emit();
}

export function useOpportunitaMap(): OpportunitaMap {
  return useSyncExternalStore(subscribe, () => snapshot);
}

export function withOpportunita(
  events: EventWithOpportunita[],
  map: OpportunitaMap,
): EventWithOpportunita[] {
  return events.map((e) => {
    const o = map[e.id];
    return o ? { ...e, opportunita: { id: e.id, idEvento: e.id, ...o } } : e;
  });
}

export function statoOf(e: EventWithOpportunita): StatoOpportunita {
  return e.opportunita?.stato ?? "non_contattato";
}

export function computeKpi(events: EventWithOpportunita[], today: Date = new Date()) {
  const month = format(today, "yyyy-MM");
  const count = (pred: (e: EventWithOpportunita) => boolean) => events.filter(pred).length;
  return {
    totaleEventi: events.length,
    questoMese: count((e) => e.dataInizio?.startsWith(month) ?? false),
    italia: count((e) => e.mercato === "italia"),
    internazionale: count((e) => e.mercato === "internazionale"),
    nonContattato: count((e) => statoOf(e) === "non_contattato"),
    contattato: count((e) => statoOf(e) === "contattato"),
    risposto: count((e) => statoOf(e) === "risposto"),
    nonRisposto: count((e) => statoOf(e) === "non_risposto"),
  };
}
