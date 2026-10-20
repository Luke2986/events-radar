import { describe, it, expect } from "vitest";
import request from "supertest";
import { buildApp } from "../../app";

describe("GET /healthz", () => {
  it("returns 200 with body {status: 'ok'}", async () => {
    const res = await request(buildApp()).get("/api/healthz");
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: "ok" });
  });
});
