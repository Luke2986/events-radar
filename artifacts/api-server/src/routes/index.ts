import { Router, type IRouter } from "express";
import healthRouter from "./health";
import eventsRouter from "./events";
import fontiRouter from "./fonti";
import kpiRouter from "./kpi";

const router: IRouter = Router();

router.use(healthRouter);
router.use("/events", eventsRouter);
router.use("/fonti", fontiRouter);
router.use("/kpi", kpiRouter);

export default router;
