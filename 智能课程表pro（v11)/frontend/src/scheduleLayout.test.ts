import { describe, expect, it } from "vitest";
import { buildScheduleLayout, gridRange, timeToSection } from "./scheduleLayout";
import type { Course, TimeSlot } from "./types";

const slots: TimeSlot[] = [
  { period: 1, start: "08:00", end: "08:45" },
  { period: 2, start: "08:55", end: "09:40" },
  { period: 3, start: "10:00", end: "10:45" },
];

const makeCourse = (
  id: string,
  section: Course["sections"][number],
): Course => ({
  id,
  name: id,
  teacher: "老师",
  color_index: 0,
  week_type: "all",
  weeks: [],
  sections: [section],
  created_at: "",
  updated_at: "",
});

describe("schedule layout", () => {
  it("places overlapping courses in separate lanes", () => {
    const layout = buildScheduleLayout(
      [
        makeCourse("A", {
          weekday: 1,
          start_period: 1,
          end_period: 2,
          location: "",
        }),
        makeCourse("B", {
          weekday: 1,
          start_period: 2,
          end_period: 3,
          location: "",
        }),
      ],
      1,
      "odd",
      [1],
      slots,
      "sections",
    );
    expect(layout.dayLayouts[0].blocks).toHaveLength(2);
    expect(layout.dayLayouts[0].blocks.every((block) => block.laneCount === 2)).toBe(true);
    expect(new Set(layout.dayLayouts[0].blocks.map((block) => block.lane))).toEqual(
      new Set([0, 1]),
    );
  });

  it("maps custom clock times into section coordinates", () => {
    expect(timeToSection("08:20", slots)).toBeCloseTo(20 / 45);
    expect(timeToSection("09:05", slots)).toBeCloseTo(1 + 10 / 45);
    expect(
      gridRange(
        {
          weekday: 1,
          start_period: 1,
          end_period: 2,
          location: "",
          custom_start: "08:20",
          custom_end: "09:05",
        },
        slots,
        "sections",
      ),
    ).toEqual([expect.closeTo(20 / 45), expect.closeTo(1 + 10 / 45)]);
  });

  it("uses absolute hour coordinates in 24-hour mode", () => {
    expect(
      gridRange(
        {
          weekday: 1,
          start_period: 1,
          end_period: 2,
          location: "",
        },
        slots,
        "24h",
      ),
    ).toEqual([8, 9 + 40 / 60]);
  });
});
