import type {
  AppConfig,
  Course,
  CourseDraft,
  ImportResult,
  ImportProfile,
  JsonImportResult,
  PlanResult,
  RescheduleResult,
  ScheduleConfig,
  SelfPlan,
  TabularImportCommitResult,
  TabularImportOptions,
  TabularImportPreview,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : detail;
    } catch {
      // Keep the status-based message when the body is not JSON.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function upload<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(path, { method: "POST", body });
  if (!response.ok) {
    let detail = `上传失败（${response.status}）`;
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : detail;
    } catch {
      // Keep the HTTP status message.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  config: () => request<AppConfig>("/api/config"),
  courses: () => request<Course[]>("/api/courses"),
  createCourse: (draft: CourseDraft) =>
    request<Course>("/api/courses", { method: "POST", body: JSON.stringify(draft) }),
  updateCourse: (id: string, draft: CourseDraft) =>
    request<Course>(`/api/courses/${id}`, { method: "PUT", body: JSON.stringify(draft) }),
  deleteCourse: (id: string) => request<void>(`/api/courses/${id}`, { method: "DELETE" }),
  importCourses: (courses: CourseDraft[]) =>
    request<Course[]>("/api/courses/import", {
      method: "POST",
      body: JSON.stringify(courses),
    }),
  importTimetable: (text: string, imageDataUrl = "") =>
    request<ImportResult>("/api/import/courses", {
      method: "POST",
      body: JSON.stringify({ text, image_data_url: imageDataUrl }),
    }),
  selfPlans: () => request<SelfPlan[]>("/api/self-plans"),
  createPlan: (plan: Omit<SelfPlan, "id" | "created_at">) =>
    request<SelfPlan>("/api/self-plans", {
      method: "POST",
      body: JSON.stringify(plan),
    }),
  deletePlan: (id: string) => request<void>(`/api/self-plans/${id}`, { method: "DELETE" }),
  aiPlan: (payload: {
    date: string;
    weekday: number;
    parity: "odd" | "even";
    free_blocks: [number, number][];
    tasks: string[];
    courses: string[];
  }) =>
    request<PlanResult>("/api/ai/plan", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  scheduleConfig: () => request<ScheduleConfig>("/api/schedule-config"),
  updateScheduleConfig: (schedule: ScheduleConfig) =>
    request<ScheduleConfig>("/api/schedule-config", {
      method: "PUT",
      body: JSON.stringify(schedule),
    }),
  previewJson: (content: string) =>
    request<JsonImportResult>("/api/import/json/preview", {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  commitJson: (courses: CourseDraft[], schedule: ScheduleConfig | null, replaceCourses: boolean) =>
    request<{ ok: boolean; imported: number }>("/api/import/json/commit", {
      method: "POST",
      body: JSON.stringify({
        courses,
        schedule,
        replace_courses: replaceCourses,
      }),
    }),
  reschedule: (payload: {
    mode: "merge" | "overwrite" | "exchange";
    source_week: number;
    source_day: number;
    target_week: number;
    target_day: number;
  }) =>
    request<RescheduleResult>("/api/courses/reschedule", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  previewTabular: (file: File, options: TabularImportOptions) => {
    const form = new FormData();
    form.append("file", file);
    Object.entries(options).forEach(([key, value]) => {
      if (key === "campus_rules") {
        form.append("campus_rules_json", JSON.stringify(value));
      } else {
        form.append(key, String(value));
      }
    });
    return upload<TabularImportPreview>("/api/import/tabular/preview", form);
  },
  commitTabular: (
    courses: CourseDraft[],
    strategy: "append" | "skip_duplicates" | "overwrite_names" | "replace",
    profile?: TabularImportOptions & { name: string },
  ) =>
    request<TabularImportCommitResult>("/api/import/tabular/commit", {
      method: "POST",
      body: JSON.stringify({ courses, strategy, profile: profile ?? null }),
    }),
  importProfiles: () => request<ImportProfile[]>("/api/import-profiles"),
  deleteImportProfile: (id: string) =>
    request<void>(`/api/import-profiles/${id}`, { method: "DELETE" }),
};
