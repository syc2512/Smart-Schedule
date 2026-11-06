import { describe, expect, it } from "vitest";
import type { Course } from "./types";
import {
  courseActive,
  courseConflicts,
  freeBlocks,
  splitBlocks,
  startOfWeek,
  toClock,
  toMinutes,
} from "./utils";

const slots = [
  { period: 1, start: "08:00", end: "08:45" },
  { period: 2, start: "08:55", end: "09:40" },
  { period: 3, start: "10:00", end: "10:45" },
  { period: 4, start: "10:55", end: "11:40" },
];

const course = (id: string, weekType: Course["week_type"] = "all"): Course => ({
  id,
  name: `课程${id}`,
  teacher: "老师",
  color_index: 0,
  week_type: weekType,
  weeks: [],
  sections: [{ weekday: 1, start_period: 1, end_period: 2, location: "A101" }],
  created_at: "",
  updated_at: "",
});

describe("timetable utilities", () => {
  it("handles week types and explicit week selections", () => {
    expect(courseActive(course("a", "all"), 3, "odd")).toBe(true);
    expect(courseActive(course("b", "even"), 3, "odd")).toBe(false);
    expect(courseActive({ ...course("c", "custom"), weeks: [2, 4] }, 4, "even")).toBe(true);
    expect(courseActive({ ...course("d", "custom"), weeks: [2, 4] }, 3, "odd")).toBe(false);
  });

  it("detects overlapping courses", () => {
    expect(courseConflicts(course("a"), [course("b")])).toHaveLength(1);
  });

  it("calculates free gaps from real period times", () => {
    const blocks = freeBlocks(
      [course("a")],
      1,
      1,
      "odd",
      slots,
      toMinutes("08:00"),
      toMinutes("11:40"),
    );
    expect(blocks).toEqual([[580, 700]]);
  });

  it("splits available blocks evenly without crossing gaps", () => {
    expect(splitBlocks([[480, 560]], 2)).toEqual([
      [480, 520],
      [520, 560],
    ]);
  });

  it("formats minute values", () => {
    expect(toClock(485)).toBe("08:05");
    expect(toClock(1440)).toBe("24:00");
  });

  it("supports a configurable first day of week", () => {
    const date = new Date(2026, 10, 5);
    expect(startOfWeek(date, 1).getDay()).toBe(1);
    expect(startOfWeek(date, 7).getDay()).toBe(0);
  });
});
