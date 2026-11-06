import { existsSync } from "node:fs";
import { chromium } from "playwright-core";

const baseUrl = process.env.BASE_URL || "http://127.0.0.1:8000";
const candidates = [
  process.env.EDGE_PATH,
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);
const executablePath = candidates.find((path) => existsSync(path));

if (!executablePath) {
  throw new Error("Set EDGE_PATH to a Chromium/Edge executable before running the E2E smoke test.");
}

const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const consoleErrors = [];
page.on("pageerror", (error) => consoleErrors.push(error.message));

const report = {};
let originalSchedule = null;
try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  originalSchedule = await page.request
    .get(`${baseUrl}/api/schedule-config`)
    .then((response) => response.json());
  report.initialRendered = await page.locator(".planner-board").isVisible();
  await page.screenshot({
    path: process.env.SCREENSHOT_PATH || "e2e-screenshot.png",
    fullPage: false,
  });

  await page.getByRole("button", { name: "添加课程" }).click();
  await page.getByPlaceholder("例如：高等数学").fill("端到端测试课程");
  await page.getByPlaceholder("例如：张老师").fill("测试教师");
  await page.getByRole("dialog").getByRole("button", { name: "精确时间" }).click();
  await page.getByLabel("开始时间").fill("08:10");
  await page.getByLabel("结束时间").fill("09:20");
  await page.getByRole("dialog").getByRole("button", { name: "添加课程", exact: true }).click();
  await page.getByText("端到端测试课程").first().waitFor();
  report.visibleAfterSave = true;
  report.conflictLayout = (await page.locator(".course-card.is-conflict").count()) > 0;

  await page.reload({ waitUntil: "networkidle" });
  report.persistedAfterReload = await page.getByText("端到端测试课程").first().isVisible();

  await page.getByRole("button", { name: "导入课表", exact: true }).click();
  await page.getByLabel("粘贴教务系统文本").fill(
    "人工智能导论 周二 第7-8节 单周 李老师 实验楼-404",
  );
  await page.getByRole("button", { name: "开始解析" }).click();
  await page.getByText("识别到 1 门课程").waitFor();
  report.importPreview = await page.getByText("本地降级解析").isVisible();
  await page.getByRole("button", { name: /确认导入 1 门课程/ }).click();
  await page.getByText("人工智能导论").first().waitFor();
  report.importPersisted = true;

  report.calendar = await page.evaluate(async () => {
    const response = await fetch("/api/export/ics?semester_start=2026-09-07&weeks=18");
    const text = await response.text();
    return {
      status: response.status,
      hasDtstamp: text.includes("DTSTAMP:"),
      hasEvent: text.includes("BEGIN:VEVENT"),
    };
  });

  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("button", { name: "导入 JSON" }).click();
  const jsonPayload = {
    schema_version: 1,
    source: "smart-timetable-pro",
    schedule: originalSchedule,
    courses: [
      {
        name: "JSON 导入测试",
        teacher: "数据老师",
        color_index: 3,
        week_type: "odd",
        weeks: [1, 3, 5],
        sections: [
          {
            weekday: 4,
            start_period: 7,
            end_period: 8,
            location: "数据楼-101",
          },
        ],
      },
    ],
  };
  await page.getByLabel("JSON 内容").fill(JSON.stringify(jsonPayload));
  await page.getByRole("button", { name: "解析并预览" }).click();
  await page.getByRole("button", { name: /确认导入 1 门课程/ }).click();
  await page.getByText("JSON 导入测试").first().waitFor();
  report.jsonImport = true;

  await page.getByRole("button", { name: "导入课表", exact: true }).click();
  await page.getByRole("button", { name: "Excel / CSV" }).click();
  const csv = Buffer.from(
    "课程名称,上课时间,上课地点,教师名称\n" +
      "CSV 导入测试,周五第7-8节{第1周},测试楼-201,数据老师\n",
  );
  await page.locator('input[type="file"][accept=".xlsx,.xls,.csv"]').setInputFiles({
    name: "测试课表.csv",
    mimeType: "text/csv",
    buffer: csv,
  });
  await page.getByRole("button", { name: "解析并预览" }).click();
  await page.getByRole("button", { name: /确认导入 1 门课程/ }).waitFor();
  await page.getByLabel("保存为导入模板").uncheck();
  await page.getByRole("button", { name: /确认导入 1 门课程/ }).click();
  await page.getByText("CSV 导入测试").first().waitFor();
  report.tabularImport = true;

  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByLabel("深色模式").check();
  await page.getByRole("button", { name: "保存全部设置" }).click();
  await page.locator('[data-theme="dark"]').waitFor();
  report.settingsSaved = true;

} finally {
  try {
    const response = await page.request.get(`${baseUrl}/api/courses`);
    const courses = await response.json();
    const temporary = courses.filter((course) =>
      ["端到端测试课程", "人工智能导论", "JSON 导入测试", "CSV 导入测试"].includes(
        course.name,
      ),
    );
    await Promise.all(
      temporary.map((course) => page.request.delete(`${baseUrl}/api/courses/${course.id}`)),
    );
    if (originalSchedule) {
      await page.request.put(`${baseUrl}/api/schedule-config`, { data: originalSchedule });
    }
  } catch {
    // Cleanup is best effort; the failed assertion above is the primary result.
  }
  report.consoleErrors = consoleErrors;
  try {
    const mobilePage = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await mobilePage.goto(baseUrl, { waitUntil: "networkidle" });
    report.mobileRendered = await mobilePage
      .getByRole("button", { name: "导入课表", exact: true })
      .isVisible();
    if (process.env.MOBILE_SCREENSHOT_PATH) {
      await mobilePage.screenshot({
        path: process.env.MOBILE_SCREENSHOT_PATH,
        fullPage: false,
      });
    }
    await mobilePage.close();
  } catch (error) {
    report.mobileRendered = false;
    report.mobileError = error instanceof Error ? error.message : String(error);
  }
  await browser.close();
}

console.log(JSON.stringify(report, null, 2));
if (
  !report.initialRendered ||
  !report.visibleAfterSave ||
  !report.conflictLayout ||
  !report.persistedAfterReload ||
  !report.importPreview ||
  !report.importPersisted ||
  !report.jsonImport ||
  !report.tabularImport ||
  !report.settingsSaved ||
  !report.mobileRendered ||
  report.calendar?.status !== 200 ||
  report.calendar?.hasDtstamp !== true ||
  report.consoleErrors?.length
) {
  process.exitCode = 1;
}
