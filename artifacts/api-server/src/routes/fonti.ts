import { Router, type IRouter } from "express";
import { FONTI } from "../data/store";

const router: IRouter = Router();

// GET /api/fonti
router.get("/", (_req, res) => {
  res.json({ fonti: FONTI });
});

export default router;
