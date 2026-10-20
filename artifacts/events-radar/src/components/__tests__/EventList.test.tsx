import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { EventWithOpportunita } from "@workspace/api-client-react";
import EventList from "../EventList";
import { STORAGE_KEY, resetOpportunitaForTests } from "../../lib/opportunita";

function makeEvent(overrides: Partial<EventWithOpportunita> = {}): EventWithOpportunita {
  return {
    id: 1,
    titolo: "Convegno Test sul LegalTech",
    dataInizio: "2026-05-15",
    dataFine: null,
    luogo: "Roma",
    lat: null,
    lng: null,
    tipoEvento: "convegno",
    organizzatore: "Org Test",
    creditiFormativi: null,
    urlSorgente: "https://example.org/ev1",
    idFonte: 1,
    mercato: "italia",
    dataInserimento: "2026-04-01T10:00:00Z",
    dataUltimoAggiornamento: "2026-04-01T10:00:00Z",
    opportunita: null,
    nomeFonte: "Fonte Test",
    ...overrides,
  } as unknown as EventWithOpportunita;
}

function renderList(events: EventWithOpportunita[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EventList events={events} />
    </QueryClientProvider>,
  );
}

function stored() {
  return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
}

beforeEach(() => {
  localStorage.clear();
  resetOpportunitaForTests();
});

describe("EventList — opportunità salvate nel browser", () => {
  it("persists the stato in localStorage when a stato pill is clicked", () => {
    renderList([makeEvent()]);
    fireEvent.click(screen.getByRole("button", { name: /^Contattato$/i }));
    expect(stored()["1"]).toMatchObject({ stato: "contattato", note: null });
  });

  it("persists the note in localStorage on blur", () => {
    renderList([makeEvent()]);
    const textarea = screen.getByRole("textbox", { name: /Note per/i });
    fireEvent.change(textarea, { target: { value: "una nota qualsiasi" } });
    fireEvent.blur(textarea);
    expect(stored()["1"]).toMatchObject({ stato: "non_contattato", note: "una nota qualsiasi" });
  });
});
