import { describe, expect, it } from "vitest";
import {
  computeRunStreak,
  computeWeeklyStrengthCount,
  startOfWeek,
} from "../src/stats.js";

function run(date, distanceMiles) {
  return { date, type: "run", distanceMiles };
}

function strength(date) {
  return { date, type: "strength" };
}

describe("computeRunStreak", () => {
  it("counts consecutive qualifying days ending today", () => {
    const entries = [run("2026-07-05", 3), run("2026-07-06", 2.5), run("2026-07-07", 2)];
    expect(computeRunStreak(entries, "2026-07-07")).toEqual({ streak: 3, todayDone: true });
  });

  it("ignores runs under the 2 mile minimum", () => {
    const entries = [run("2026-07-06", 3), run("2026-07-07", 1.5)];
    expect(computeRunStreak(entries, "2026-07-07")).toEqual({ streak: 1, todayDone: false });
  });

  it("still counts yesterday's streak when today is not logged yet", () => {
    const entries = [run("2026-07-05", 3), run("2026-07-06", 2)];
    expect(computeRunStreak(entries, "2026-07-07")).toEqual({ streak: 2, todayDone: false });
  });

  it("resets to zero after a missed day", () => {
    const entries = [run("2026-07-04", 3), run("2026-07-05", 2)];
    expect(computeRunStreak(entries, "2026-07-07")).toEqual({ streak: 0, todayDone: false });
  });

  it("dedupes multiple runs logged on the same day", () => {
    const entries = [run("2026-07-07", 2), run("2026-07-07", 3)];
    expect(computeRunStreak(entries, "2026-07-07")).toEqual({ streak: 1, todayDone: true });
  });
});

describe("startOfWeek", () => {
  it("returns the Monday of the containing week", () => {
    expect(startOfWeek("2026-07-07")).toBe("2026-07-06"); // Tuesday -> Monday
    expect(startOfWeek("2026-07-06")).toBe("2026-07-06"); // Monday -> itself
    expect(startOfWeek("2026-07-12")).toBe("2026-07-06"); // Sunday -> preceding Monday
  });
});

describe("computeWeeklyStrengthCount", () => {
  it("counts unique strength days within the current Mon-Sun week", () => {
    const entries = [
      strength("2026-07-06"), // Mon (this week)
      strength("2026-07-07"), // Tue (this week)
      strength("2026-07-05"), // Sun (last week, excluded)
    ];
    const result = computeWeeklyStrengthCount(entries, "2026-07-07");
    expect(result).toEqual({
      count: 2,
      goalMin: 4,
      goalMax: 5,
      weekStart: "2026-07-06",
      weekEnd: "2026-07-12",
    });
  });

  it("counts a day only once even with multiple sessions logged", () => {
    const entries = [strength("2026-07-06"), strength("2026-07-06")];
    expect(computeWeeklyStrengthCount(entries, "2026-07-07").count).toBe(1);
  });
});
