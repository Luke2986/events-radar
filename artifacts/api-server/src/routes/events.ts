import { Router, type IRouter } from "express";
import { ListEventsQueryParams, GetEventParams } from "@workspace/api-zod";
import { EVENTS, filterEvents } from "../data/store";

const router: IRouter = Router();

// GET /api/events
router.get("/", (req, res) => {
  const parsed = ListEventsQueryParams.safeParse(req.query);
  if (!parsed.success) {
    const details = parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`);
    res.status(400).json({ error: "Invalid query params", details });
    return;
  }

  const { limit = 200, offset = 0, ...filters } = parsed.data;
  const matching = filterEvents(filters);
  res.json({ events: matching.slice(offset, offset + limit), total: matching.length });
});

// GET /api/events/:id
router.get("/:id", (req, res) => {
  const parsed = GetEventParams.safeParse({ id: Number(req.params.id) });
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid id" });
    return;
  }

  const event = EVENTS.find((e) => e.id === parsed.data.id);
  if (!event) {
    res.status(404).json({ error: "Event not found" });
    return;
  }
  res.json(event);
});

export default router;
