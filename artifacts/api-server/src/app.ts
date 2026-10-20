import express, { type Express } from "express";
import cors from "cors";
import pinoHttp from "pino-http";
import rateLimit from "express-rate-limit";
import router from "./routes";
import { logger } from "./lib/logger";

/**
 * Builds and configures the Express application (middleware + routes).
 * No side-effects: does NOT call `app.listen()`. Safe for use in tests
 * via `supertest(buildApp())`.
 */
export function buildApp(): Express {
  const app: Express = express();

  // Trust the first proxy hop so that express-rate-limit can read
  // X-Forwarded-For without throwing ERR_ERL_UNEXPECTED_X_FORWARDED_FOR.
  app.set("trust proxy", 1);

  app.use(
    pinoHttp({
      logger,
      serializers: {
        req(req) {
          return {
            id: req.id,
            method: req.method,
            url: req.url?.split("?")[0],
          };
        },
        res(res) {
          return {
            statusCode: res.statusCode,
          };
        },
      },
    }),
  );
  app.use(cors());
  app.use(express.json());
  app.use(express.urlencoded({ extended: true }));

  const RATE_LIMIT_BODY = { error: "Too many requests, please try again later." };

  const readLimiter = rateLimit({
    windowMs: 60_000,
    max: 60,
    standardHeaders: true,
    legacyHeaders: false,
    message: RATE_LIMIT_BODY,
  });

  const writeLimiter = rateLimit({
    windowMs: 60_000,
    max: 30,
    standardHeaders: true,
    legacyHeaders: false,
    message: RATE_LIMIT_BODY,
  });

  app.use("/api", (req, res, next) => {
    const isWrite = ["POST", "PATCH", "PUT", "DELETE"].includes(req.method);
    return (isWrite ? writeLimiter : readLimiter)(req, res, next);
  });

  app.use("/api", router);

  return app;
}

// Default export preserves backward compatibility with existing imports.
const app = buildApp();
export default app;
