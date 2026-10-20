import { Router, type IRouter } from "express";
import { GetKpiQueryParams } from "@workspace/api-zod";
import { computeKpi, filterEvents } from "../data/store";

const router: IRouter = Router();

// GET /api/kpi
router.get("/", (req, res) => {
  const parsed = GetKpiQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid query params" });
    return;
  }
  res.json(computeKpi(filterEvents(parsed.data)));
});

export default router;
