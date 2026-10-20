import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// vitest config has `globals: false`, so RTL's auto-cleanup hook isn't
// registered automatically — wire it up explicitly to unmount between tests.
afterEach(() => {
  cleanup();
});
