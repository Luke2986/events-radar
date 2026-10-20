import { describe, it, expect } from "vitest";
import request from "supertest";
import { GetEventResponse, ListEventsResponse, ListFontiResponse } from "@workspace/api-zod";
import { buildApp } from "../../app";
import { EVENTS } from "../../data/store";

const app = buildApp();

describe("GET /api/events", () => {
  it("returns a response conforming to ListEventsResponse", async () => {
    const res = await request(app).get("/api/events?includi_passati=true");
    expect(res.status).toBe(200);
    expect(ListEventsResponse.safeParse(res.body).success).toBe(true);
    expect(res.body.total).toBe(EVENTS.length);
  });

  it("respects limit and offset while reporting the full total", async () => {
    const res = await request(app).get("/api/events?includi_passati=true&limit=2&offset=1");
    expect(res.status).toBe(200);
    expect(res.body.events).toHaveLength(2);
    expect(res.body.total).toBe(EVENTS.length);
  });

  it("filters by mercato", async () => {
    const res = await request(app).get("/api/events?includi_passati=true&mercato=italia");
    expect(res.body.events.length).toBeGreaterThan(0);
    expect(res.body.events.every((e: { mercato: string }) => e.mercato === "italia")).toBe(true);
  });

  it("rejects limit=-1 with 400 (Zod validation)", async () => {
    const res = await request(app).get("/api/events?limit=-1");
    expect(res.status).toBe(400);
  });

  it("rejects offset=-1 with 400 (Zod validation)", async () => {
    const res = await request(app).get("/api/events?offset=-1");
    expect(res.status).toBe(400);
  });
});

describe("GET /api/events/:id", () => {
  it("returns the event conforming to GetEventResponse", async () => {
    const res = await request(app).get(`/api/events/${EVENTS[0].id}`);
    expect(res.status).toBe(200);
    expect(GetEventResponse.safeParse(res.body).success).toBe(true);
  });

  it("returns 404 for an unknown id", async () => {
    const res = await request(app).get("/api/events/999999");
    expect(res.status).toBe(404);
  });
});

describe("GET /api/fonti", () => {
  it("returns sources conforming to ListFontiResponse with event counts", async () => {
    const res = await request(app).get("/api/fonti");
    expect(res.status).toBe(200);
    expect(ListFontiResponse.safeParse(res.body).success).toBe(true);
    const total = res.body.fonti.reduce((n: number, f: { conteggioEventi: number }) => n + f.conteggioEventi, 0);
    expect(total).toBe(EVENTS.filter((e) => e.idFonte !== null).length);
  });
});
