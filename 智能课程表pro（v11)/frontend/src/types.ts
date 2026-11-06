export type WeekType = "all" | "odd" | "even" | "custom";

export interface CourseSection {
  weekday: number;
  start_period: number;
  end_period: number;
  location: string;
  custom_start?: string | null;
  custom_end?: string | null;
}

export interface CourseDraft {
  name: string;
  teacher: string;
  color_index: number;
  week_type: WeekType;
  weeks: number[];
  sections: CourseSection[];
}

export interface Course extends CourseDraft {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface SelfPlan {
  id: string;
  title: string;
  date: string;
  weekday: number;
  start_min: number;
  end_min: number;
  notes: string;
  category: "personal" | "kg" | "kaoyan" | "study";
  created_at: string;
}

export interface TimeSlot {
  period: number;
  start: string;
  end: string;
  alias?: string;
}

export interface TimetableSettings {
  name: string;
  semester_start_date: string;
  total_weeks: number;
  first_day_of_week: number;
  show_weekends: boolean;
  display_mode: "sections" | "24h";
  density: "compact" | "comfortable";
  background_theme: "paper" | "mint" | "warm" | "slate";
  dark_mode: boolean;
  card_opacity: number;
  hide_teacher: boolean;
  hide_location: boolean;
  font_scale: number;
}

export interface Holiday {
  date: string;
  name: string;
}

export interface ScheduleConfig {
  settings: TimetableSettings;
  time_slots: TimeSlot[];
  holidays: Holiday[];
}

export interface AppConfig {
  time_slots: TimeSlot[];
  color_palette: { bg: string; stripe: string }[];
  total_weeks: number;
  ai_enabled: boolean;
  settings: TimetableSettings;
  holidays: Holiday[];
}

export interface ImportResult {
  ok: boolean;
  degraded: boolean;
  reason: string | null;
  model: string | null;
  courses: CourseDraft[];
  warnings: string[];
}

export interface PlanResult {
  ok: boolean;
  degraded: boolean;
  reason: string | null;
  model: string | null;
  plan: string;
}

export interface JsonImportResult {
  ok: boolean;
  source: "smart-timetable-pro" | "shiguangschedule" | "unknown";
  courses: CourseDraft[];
  schedule: ScheduleConfig | null;
  warnings: string[];
}

export interface RescheduleResult {
  ok: boolean;
  moved: number;
  removed_target_occurrences: number;
  warnings: string[];
}

export interface TabularImportOptions {
  header_row: number;
  course_column: string;
  time_column: string;
  location_column: string;
  teacher_column: string;
  multi_separator: string;
  odd_marker: string;
  even_marker: string;
  time_regex: string;
  campus_rules: Record<string, TimeSlot[]>;
}

export interface TabularImportPreview {
  ok: boolean;
  source_name: string;
  sheet_name: string | null;
  rows_read: number;
  skipped_rows: number;
  detected_columns: Record<string, string>;
  headers: string[];
  courses: CourseDraft[];
  warnings: string[];
}

export interface ImportProfile extends TabularImportOptions {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface TabularImportCommitResult {
  ok: boolean;
  imported: number;
  skipped: number;
  profile_id: string | null;
  warnings: string[];
}
