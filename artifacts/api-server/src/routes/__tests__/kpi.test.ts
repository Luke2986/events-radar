import { describe, it, expect } from "vitest";
import request from "supertest";
import { GetKpiResponse } from "@workspace/api-zod";
import { buildApp } from "../../app";
import { EVENTS, computeKpi, filterEvents } from "../../data/store";

describe("GET /api/kpi", () => {
  it("returns 200 with an object conforming to GetKpiResponse", async () => {
    const res = await request(buildApp()).get("/api/kpi?includi_passati=true");
    expect(res.status).toBe(200);
    expect(GetKpiResponse.safeParse(res.body).success).toBe(true);
    expect(res.body.totaleEventi).toBe(EVENTS.length);
    expect(res.body.italia + res.body.internazionale).toBe(EVENTS.length);
  });
});

describe("filterEvents", () => {
  const today = "2026-11-01";

  it("hides events that ended before today unless includi_passati", () => {
    const visible = filterEvents({}, today);
    expect(visible.every((e) => (e.dataFine ?? e.dataInizio)! >= today)).toBe(true);
    expect(filterEvents({ includi_passati: true }, today).length).toBeGreaterThan(visible.length);
  });

  it("matches luogo case-insensitively as a substring", () => {
    const res = filterEvents({ luogo: "lONDON", includi_passati: true }, today);
    expect(res.length).toBeGreaterThan(0);
    expect(res.every((e) => e.luogo?.toLowerCase().includes("london"))).toBe(true);
  });

  it("applies data_da / data_a on dataInizio", () => {
    const res = filterEvents({ data_da: "2026-11-01", data_a: "2026-11-10", includi_passati: true }, today);
    expect(res.length).toBeGreaterThan(0);
    expect(res.every((e) => e.dataInizio! >= "2026-11-01" && e.dataInizio! <= "2026-11-10")).toBe(true);
  });

  it("returns events sorted by dataInizio", () => {
    const dates = filterEvents({ includi_passati: true }, today).map((e) => e.dataInizio ?? "9999");
    expect(dates).toEqual([...dates].sort());
  });
});

describe("computeKpi", () => {
  it("counts events starting in the current month", () => {
    const kpi = computeKpi(EVENTS, "2026-11-15");
    expect(kpi.questoMese).toBe(EVENTS.filter((e) => e.dataInizio?.startsWith("2026-11")).length);
  });
});
