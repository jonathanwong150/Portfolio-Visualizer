import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest's globals don't auto-unmount React trees between tests.
afterEach(cleanup);

// jsdom has no ResizeObserver, and recharts' ResponsiveContainer constructs one
// in a passive effect — without this the throw tears down the whole tree and
// every assertion after a chart renders fails with a bare "element not found".
class ResizeObserverStub implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub;
