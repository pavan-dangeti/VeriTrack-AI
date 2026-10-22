import { describe, expect, it } from "vitest";
import { pollDelay } from "../api/hooks";

const now = Date.parse("2026-10-20T12:00:00Z");
const ago = (s: number) => new Date(now - s * 1000).toISOString();

describe("pollDelay", () => {
  it("polls fast while work is fresh and slows to every 10 s as it waits", () => {
    expect(pollDelay([ago(0)], now)).toBe(1_500);
    expect(pollDelay([ago(9)], now)).toBe(1_500);
    expect(pollDelay([ago(30)], now)).toBe(5_000);
    expect(pollDelay([ago(60)], now)).toBe(10_000);
    expect(pollDelay([ago(900)], now)).toBe(10_000);
  });

  it("follows the newest in-flight item, so a fresh upload updates quickly", () => {
    expect(pollDelay([ago(600), ago(3)], now)).toBe(1_500);
  });

  it("polls fast when it cannot tell the age", () => {
    expect(pollDelay([], now)).toBe(1_500);
    expect(pollDelay([null, undefined], now)).toBe(1_500);
  });
});
