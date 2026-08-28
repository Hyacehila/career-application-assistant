import { expect } from "vitest";
import * as jestDom from "@testing-library/jest-dom/matchers";

expect.extend(jestDom);

// jsdom does not provide window.matchMedia. Provide a minimal polyfill that
// honours an optional controllable entry point: tests can set
// `window.__matchMediaMock` (a function returning a MediaQueryList-like
// object) before rendering to override the default `matches: false` behaviour.
type MatchMediaMockFn = (query: string) => {
  matches: boolean;
  media?: string;
  onchange?: null;
  addEventListener?: (type: string, listener: () => void) => void;
  removeEventListener?: (type: string, listener: () => void) => void;
  addListener?: (listener: () => void) => void;
  removeListener?: (listener: () => void) => void;
  dispatchEvent?: (event?: unknown) => boolean;
  [key: string]: unknown;
};

declare global {
  interface Window {
    __matchMediaMock?: MatchMediaMockFn;
  }
}

if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => {
      if (window.__matchMediaMock) {
        const overridden = window.__matchMediaMock(query);
        if (overridden) return overridden;
      }
      return {
        matches: false,
        media: query,
        onchange: null,
        addEventListener() {},
        removeEventListener() {},
        addListener() {},
        removeListener() {},
        dispatchEvent: () => false,
      };
    },
  });
}
