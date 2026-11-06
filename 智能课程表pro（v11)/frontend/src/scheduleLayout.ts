import type { Course, CourseSection, TimeSlot } from "./types";
import { courseActive, sectionMinutes, toMinutes } from "./utils";

export interface CourseBlockLayout {
  course: Course;
  section: CourseSection;
  sectionIndex: number;
  start: number;
  end: number;
  lane: number;
  laneCount: number;
  clusterId: string;
}

export interface DayLayout {
  weekday: number;
  blocks: CourseBlockLayout[];
}

export interface ScheduleLayout {
  axisCount: number;
  dayLayouts: DayLayout[];
}

export function buildScheduleLayout(
  courses: Course[],
  weekNumber: number,
  parity: "odd" | "even",
  weekdayOrder: number[],
  slots: TimeSlot[],
  mode: "sections" | "24h",
): ScheduleLayout {
  const dayLayouts: DayLayout[] = weekdayOrder.map((weekday) => ({
    weekday,
    blocks: layoutDay(
      courses.filter((course) => courseActive(course, weekNumber, parity)),
      weekday,
      slots,
      mode,
    ),
  }));
  return {
    axisCount: mode === "24h" ? 24 : Math.max(1, slots.length),
    dayLayouts,
  };
}

function layoutDay(
  courses: Course[],
  weekday: number,
  slots: TimeSlot[],
  mode: "sections" | "24h",
): CourseBlockLayout[] {
  const normalized: Omit<CourseBlockLayout, "lane" | "laneCount" | "clusterId">[] = [];
  courses.forEach((course) => {
    course.sections.forEach((section, sectionIndex) => {
      if (section.weekday !== weekday) return;
      const [start, end] = gridRange(section, slots, mode);
      if (end <= start) return;
      normalized.push({ course, section, sectionIndex, start, end });
    });
  });
  normalized.sort((a, b) => a.start - b.start || b.end - a.end);

  const result: CourseBlockLayout[] = [];
  let cluster: typeof normalized = [];
  let clusterEnd = -Infinity;
  let clusterIndex = 0;

  const flush = () => {
    if (!cluster.length) return;
    const lanes: number[] = [];
    const assignments = cluster.map((item) => {
      let lane = lanes.findIndex((laneEnd) => laneEnd <= item.start + 0.001);
      if (lane < 0) {
        lane = lanes.length;
        lanes.push(item.end);
      } else {
        lanes[lane] = item.end;
      }
      return { ...item, lane };
    });
    assignments.forEach((item) => {
      result.push({
        ...item,
        laneCount: lanes.length,
        clusterId: `cluster-${weekday}-${clusterIndex}`,
      });
    });
    clusterIndex += 1;
    cluster = [];
    clusterEnd = -Infinity;
  };

  normalized.forEach((item) => {
    if (cluster.length && item.start >= clusterEnd - 0.001) flush();
    cluster.push(item);
    clusterEnd = Math.max(clusterEnd, item.end);
  });
  flush();
  return result;
}

export function gridRange(
  section: CourseSection,
  slots: TimeSlot[],
  mode: "sections" | "24h",
): [number, number] {
  if (mode === "24h") {
    const [start, end] = sectionMinutes(section, slots);
    return [start / 60, end / 60];
  }
  if (section.custom_start && section.custom_end) {
    return [
      timeToSection(section.custom_start, slots),
      timeToSection(section.custom_end, slots),
    ];
  }
  return [section.start_period - 1, section.end_period];
}

export function timeToSection(clock: string, slots: TimeSlot[]): number {
  const value = toMinutes(clock);
  if (!slots.length) return 0;
  for (let index = 0; index < slots.length; index += 1) {
    const start = toMinutes(slots[index].start);
    const end = toMinutes(slots[index].end);
    if (value <= start) return index;
    if (value <= end) return index + (value - start) / Math.max(1, end - start);
  }
  return slots.length;
}

export function axisLabel(
  mode: "sections" | "24h",
  index: number,
  slots: TimeSlot[],
): { primary: string; start: string; end: string } {
  if (mode === "24h") {
    const start = `${String(index - 1).padStart(2, "0")}:00`;
    return { primary: String(index), start, end: `${String(index).padStart(2, "0")}:00` };
  }
  const slot = slots[index - 1];
  return {
    primary: String(slot?.period ?? index),
    start: slot?.start ?? "—",
    end: slot?.end ?? "—",
  };
}
