import "@testing-library/jest-dom/vitest";

// AG Grid requires ResizeObserver + measured containers; jsdom has neither.
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!("ResizeObserver" in globalThis)) {
  (globalThis as unknown as Record<string, unknown>).ResizeObserver = ResizeObserverMock;
}

// jsdom reports 0x0 everywhere; give grids a nominal size so rows mount.
Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
  configurable: true,
  get() {
    return this.tagName === "BODY" ? 800 : 400;
  },
});
Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
  configurable: true,
  get() {
    return this.tagName === "BODY" ? 1200 : 900;
  },
});
