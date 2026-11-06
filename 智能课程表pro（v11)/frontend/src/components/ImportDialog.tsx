import { useRef, useState } from "react";
import { api } from "../api";
import type { CourseDraft, ImportResult } from "../types";
import { WEEKDAYS } from "../utils";
import { Icon } from "./Icon";
import { Modal } from "./Modal";

const EXAMPLE = `高等数学　周一 第1-2节　1-16周　张老师　教三-201
大学英语　周一 第3-4节　1-16周　李老师　外语楼-305
离散数学　周三 第5-6节　单周　孙老师　教三-208`;

export function ImportDialog({
  onClose,
  onImported,
  onOpenTabular,
}: {
  onClose: () => void;
  onImported: (count: number) => Promise<void>;
  onOpenTabular: () => void;
}) {
  const [text, setText] = useState("");
  const [imageDataUrl, setImageDataUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const chooseImage = (file: File | undefined) => {
    setError("");
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("请选择图片文件");
      return;
    }
    if (file.size > 6 * 1024 * 1024) {
      setError("图片不能超过 6MB");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setImageDataUrl(String(reader.result ?? ""));
      setFileName(file.name);
      setResult(null);
    };
    reader.onerror = () => setError("图片读取失败");
    reader.readAsDataURL(file);
  };

  const parse = async () => {
    setError("");
    if (!text.trim() && !imageDataUrl) {
      setError("请输入教务文本或选择排课截图");
      return;
    }
    setBusy(true);
    try {
      const response = await api.importTimetable(text, imageDataUrl);
      setResult(response);
      setSelected(new Set(response.courses.map((_, index) => index)));
      if (!response.courses.length) {
        setError(response.warnings.join("；") || "未识别到课程");
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "解析失败");
    } finally {
      setBusy(false);
    }
  };

  const toggleCourse = (index: number) => {
    const next = new Set(selected);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setSelected(next);
  };

  const confirm = async () => {
    if (!result) return;
    const courses = result.courses.filter((_, index) => selected.has(index));
    if (!courses.length) {
      setError("请至少选择一门课程");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.importCourses(courses);
      await onImported(courses.length);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="AI 导入课表" eyebrow="文本 / 截图解析" onClose={onClose} wide>
      <div className="import-mode-tabs">
        <button className="active" type="button">AI 文本 / 截图</button>
        <button type="button" onClick={onOpenTabular}>Excel / CSV</button>
      </div>
      <div className="import-layout">
        <section>
          <label className="field">
            <span>粘贴教务系统文本</span>
            <textarea
              rows={7}
              maxLength={20_000}
              value={text}
              onChange={(event) => {
                setText(event.target.value);
                setResult(null);
              }}
              placeholder={EXAMPLE}
            />
          </label>
          <button
            className="text-button"
            type="button"
            onClick={() => {
              setText(EXAMPLE);
              setResult(null);
            }}
          >
            填入示例
          </button>
        </section>
        <section className="image-upload-panel">
          <span>或上传排课截图</span>
          <input
            ref={fileRef}
            hidden
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => chooseImage(event.target.files?.[0])}
          />
          {imageDataUrl ? (
            <div className="image-preview">
              <img src={imageDataUrl} alt="待解析的课表截图" />
              <div>
                <strong>{fileName}</strong>
                <button
                  className="text-button danger"
                  type="button"
                  onClick={() => {
                    setImageDataUrl("");
                    setFileName("");
                    setResult(null);
                    if (fileRef.current) fileRef.current.value = "";
                  }}
                >
                  移除
                </button>
              </div>
            </div>
          ) : (
            <button
              className="upload-drop"
              type="button"
              onClick={() => fileRef.current?.click()}
            >
              <Icon name="import" size={28} />
              <strong>选择一张课表图片</strong>
              <span>PNG / JPG / WebP，最大 6MB</span>
            </button>
          )}
        </section>
      </div>

      <div className="import-action-row">
        <p>
          模型只生成草稿。确认前会通过 Pydantic 校验，不会直接覆盖现有课程。
        </p>
        <button className="button primary" type="button" onClick={parse} disabled={busy}>
          <Icon name="spark" />
          {busy ? "解析中…" : "开始解析"}
        </button>
      </div>

      {error && <div className="notice error">{error}</div>}

      {result && (
        <section className="preview-panel">
          <div className="preview-head">
            <div>
              <p className="eyebrow">解析结果</p>
              <h3>
                识别到 {result.courses.length} 门课程
                {selected.size > 0 && <span className="muted"> · 已选 {selected.size}</span>}
              </h3>
            </div>
            <div className="preview-badges">
              <span className={`status-badge ${result.degraded ? "amber" : "green"}`}>
                {result.degraded ? "本地降级解析" : `AI · ${result.model ?? "结构化解析"}`}
              </span>
            </div>
          </div>
          {result.warnings.length > 0 && (
            <div className="notice warning">
              <Icon name="warning" />
              {result.warnings.join("；")}
            </div>
          )}
          <div className="preview-courses">
            {result.courses.map((course, index) => (
              <label
                className={`preview-course ${selected.has(index) ? "selected" : ""}`}
                key={`${course.name}-${index}`}
              >
                <input
                  type="checkbox"
                  checked={selected.has(index)}
                  onChange={() => toggleCourse(index)}
                />
                <div className="preview-course-main">
                  <strong>{course.name}</strong>
                  <span>
                    {course.sections
                      .map(
                        (section) =>
                          `${WEEKDAYS[section.weekday - 1]} 第${section.start_period}-${section.end_period}节`,
                      )
                      .join("；")}
                  </span>
                  <span>
                    {course.teacher || "教师未知"} · {course.sections[0]?.location || "地点未知"}
                  </span>
                </div>
                <em>{weekTypeLabel(course)}</em>
              </label>
            ))}
          </div>
          <div className="modal-actions">
            <span className="action-spacer" />
            <button className="button ghost" type="button" onClick={onClose}>
              取消
            </button>
            <button
              className="button primary"
              type="button"
              onClick={confirm}
              disabled={busy || selected.size === 0}
            >
              确认导入 {selected.size} 门课程
            </button>
          </div>
        </section>
      )}
    </Modal>
  );
}

function weekTypeLabel(course: CourseDraft): string {
  if (course.week_type === "odd") return "单周";
  if (course.week_type === "even") return "双周";
  if (course.week_type === "custom") return `${course.weeks.length} 个指定周`;
  return "每周";
}
