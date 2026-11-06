import type { Course, CourseSection, SelfPlan, TimeSlot } from "./types";

export const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

export function toMinutes(clock: string): number {
  const [hour, minute] = clock.split(":").map(Number);
  return hour * 60 + minute;
}

export function toClock(minutes: number): string {
  const safe = Math.max(0, Math.min(1440, Math.round(minutes)));
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function mondayOf(date: Date): Date {
  return startOfWeek(date, 1);
}

export function startOfWeek(date: Date, firstDay = 1): Date {
  const next = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const current = next.getDay() === 0 ? 7 : next.getDay();
  next.setDate(next.getDate() - ((current - firstDay + 7) % 7));
  return next;
}

export function dateString(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")}`;
}

export function weekDates(start: Date, offset: number, firstDay = 1): Date[] {
  const weekStart = addDays(startOfWeek(start, firstDay), offset * 7);
  return Array.from({ length: 7 }, (_, index) => addDays(weekStart, index));
}

export function parityForOffset(offset: number): "odd" | "even" {
  return (offset + 1) % 2 === 1 ? "odd" : "even";
}

export function weekOffsetForDate(date: Date, semesterStart: Date, firstDay = 1): number {
  return Math.round(
    (startOfWeek(date, firstDay).getTime() - startOfWeek(semesterStart, firstDay).getTime()) /
      (7 * 86_400_000),
  );
}

export function parityForDate(
  date: Date,
  semesterStart: Date,
  firstDay = 1,
): "odd" | "even" {
  const offset = weekOffsetForDate(date, semesterStart, firstDay);
  return parityForOffset(offset);
}

export function courseActive(
  course: Course,
  weekNumber: number,
  parity: "odd" | "even",
): boolean {
  if (course.weeks.length) return course.weeks.includes(weekNumber);
  if (course.week_type === "all") return true;
  return course.week_type === parity;
}

export function sectionsOverlap(a: CourseSection, b: CourseSection): boolean {
  return (
    a.weekday === b.weekday &&
    a.start_period <= b.end_period &&
    b.start_period <= a.end_period
  );
}

export function courseConflicts(course: Course, others: Course[]): Course[] {
  return others.filter(
    (other) =>
      (course.week_type === "all" ||
        other.week_type === "all" ||
        course.week_type === other.week_type) &&
      course.sections.some((section) =>
        other.sections.some((candidate) => sectionsOverlap(section, candidate)),
      ),
  );
}

export function freeBlocks(
  courses: Course[],
  weekNumber: number,
  weekday: number,
  parity: "odd" | "even",
  slots: TimeSlot[],
  startMinute =
    slots.length > 0 ? toMinutes(slots[0].start) : 480,
  endMinute =
    slots.length > 0 ? toMinutes(slots[slots.length - 1].end) : 1350,
): [number, number][] {
  const slotMap = new Map(slots.map((slot) => [slot.period, slot]));
  const occupied = courses
    .filter((course) => courseActive(course, weekNumber, parity))
    .flatMap((course) => course.sections)
    .filter((section) => section.weekday === weekday)
    .map((section) => [
      section.custom_start
        ? toMinutes(section.custom_start)
        : toMinutes(slotMap.get(section.start_period)?.start ?? "00:00"),
      section.custom_end
        ? toMinutes(section.custom_end)
        : toMinutes(slotMap.get(section.end_period)?.end ?? "00:00"),
    ] as [number, number])
    .sort((a, b) => a[0] - b[0]);

  const result: [number, number][] = [];
  let cursor = startMinute;
  for (const [start, end] of occupied) {
    if (start - cursor >= 20) result.push([cursor, start]);
    cursor = Math.max(cursor, end);
  }
  if (endMinute - cursor >= 20) result.push([cursor, endMinute]);
  return result;
}

export function sectionMinutes(
  section: CourseSection,
  slots: TimeSlot[],
): [number, number] {
  if (section.custom_start && section.custom_end) {
    return [toMinutes(section.custom_start), toMinutes(section.custom_end)];
  }
  const slotMap = new Map(slots.map((slot) => [slot.period, slot]));
  return [
    toMinutes(slotMap.get(section.start_period)?.start ?? "08:00"),
    toMinutes(slotMap.get(section.end_period)?.end ?? "08:45"),
  ];
}

export function splitBlocks(
  blocks: [number, number][],
  taskCount: number,
  minLength = 20,
): [number, number][] {
  const valid = blocks.filter(([start, end]) => end > start).sort((a, b) => a[0] - b[0]);
  const total = valid.reduce((sum, [start, end]) => sum + end - start, 0);
  if (taskCount < 1 || total < taskCount * minLength) return [];

  const result: [number, number][] = [];
  let blockIndex = 0;
  let cursor = valid[0]?.[0] ?? 0;
  let blockEnd = valid[0]?.[1] ?? 0;
  const base = Math.floor(total / taskCount);
  const remainder = total % taskCount;

  for (let index = 0; index < taskCount; index += 1) {
    let wanted = base + (index < remainder ? 1 : 0);
    while (blockEnd - cursor < wanted && blockIndex < valid.length - 1) {
      blockIndex += 1;
      cursor = valid[blockIndex][0];
      blockEnd = valid[blockIndex][1];
    }
    wanted = Math.min(wanted, blockEnd - cursor);
    result.push([cursor, cursor + wanted]);
    cursor += wanted;
    if (cursor >= blockEnd && blockIndex < valid.length - 1) {
      blockIndex += 1;
      cursor = valid[blockIndex][0];
      blockEnd = valid[blockIndex][1];
    }
  }
  return result;
}

export function planForDate(plans: SelfPlan[], date: Date): SelfPlan[] {
  const target = dateString(date);
  return plans.filter((plan) => plan.date === target);
}

export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours ? `${hours}小时${rest ? `${rest}分` : ""}` : `${rest}分钟`;
}
