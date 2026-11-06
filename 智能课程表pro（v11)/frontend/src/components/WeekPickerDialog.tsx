import { Modal } from "./Modal";

export function WeekPickerDialog({
  currentWeek,
  todayWeek,
  totalWeeks,
  onSelect,
  onClose,
}: {
  currentWeek: number;
  todayWeek: number;
  totalWeeks: number;
  onSelect: (weekOffset: number) => void;
  onClose: () => void;
}) {
  return (
    <Modal title="快速跳转周次" eyebrow="学期周次" onClose={onClose}>
      <div className="week-jump-grid">
        {Array.from({ length: totalWeeks }, (_, index) => index + 1).map((week) => (
          <button
            className={[
              week === currentWeek + 1 ? "selected" : "",
              week === todayWeek ? "is-current-date" : "",
            ].join(" ")}
            type="button"
            key={week}
            onClick={() => {
              onSelect(week - 1);
              onClose();
            }}
          >
            <strong>第 {week} 周</strong>
            <span>{week % 2 === 1 ? "单周" : "双周"}</span>
            {week === todayWeek && <em>本周</em>}
          </button>
        ))}
      </div>
    </Modal>
  );
}
