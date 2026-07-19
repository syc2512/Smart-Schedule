/* ============================================================
 * timetable-core.js — 智能课程表 Pro 纯函数内核
 * ------------------------------------------------------------
 * 零依赖、零构建。通过双环境导出：
 *   - 浏览器：挂载到 window.STPCore（供 smart-timetable-pro.html 薄包装调用）
 *   - Node：module.exports（供 tests/test_core.mjs 用 createRequire 引入）
 *
 * 约定：本文件中的函数不引用 document / window / $ / DATA / state 等
 *       浏览器全局；一切外部依赖（时间/格式化/数据）均经参数注入，
 *       以便 Node 单测使用 fixture 注入。
 * ============================================================ */
(function (global) {
  "use strict";

  /* ---------- idleBlocks：计算一天内的空闲时间段 ---------- */
  function idleBlocks(courses, ctx) {
    ctx = ctx || {};
    var dayStartMinutes = ctx.dayStartMinutes != null ? ctx.dayStartMinutes : 0;
    var dayEndMinutes = ctx.dayEndMinutes != null ? ctx.dayEndMinutes : 1440;
    var timeSlots = ctx.timeSlots || [];
    var toMin = ctx.toMin || function (hm) {
      var a = String(hm).split(":");
      return (+a[0]) * 60 + (+a[1]);
    };

    var pts = [dayStartMinutes];
    courses.forEach(function (item) {
      var c = item.section || item;
      if (!c) return;
      var sp = c.startPeriod, ep = c.endPeriod;
      if (sp == null || ep == null) return;
      if (!timeSlots[sp - 1] || !timeSlots[ep - 1]) return;
      pts.push(toMin(timeSlots[sp - 1].start));
      pts.push(toMin(timeSlots[ep - 1].end));
    });
    pts.push(dayEndMinutes);
    pts.sort(function (a, b) { return a - b; });

    var blocks = [];
    for (var i = 0; i < pts.length - 1; i++) {
      var s = pts[i], e = pts[i + 1];
      var covered = courses.some(function (item) {
        var c = item.section || item;
        if (!c || c.startPeriod == null || c.endPeriod == null) return false;
        if (!timeSlots[c.startPeriod - 1] || !timeSlots[c.endPeriod - 1]) return false;
        var cs = toMin(timeSlots[c.startPeriod - 1].start);
        var ce = toMin(timeSlots[c.endPeriod - 1].end);
        return s >= cs && e <= ce && s < e;
      });
      if (!covered && e - s >= 20) blocks.push({ s: s, e: e });
    }
    return blocks;
  }

  /* ---------- deriveWeekType：由周次数组推导周次类型 ---------- */
  function deriveWeekType(weeks, totalWeeks) {
    weeks = weeks || [];
    totalWeeks = totalWeeks || 0;
    if (weeks.length === totalWeeks) return "all";
    if (weeks.length === Math.ceil(totalWeeks / 2) && weeks[0] === 1) return "odd";
    if (weeks.length === Math.floor(totalWeeks / 2) && weeks[0] === 2) return "even";
    return "custom";
  }

  /* ---------- validateCourseForm：课程表单校验 ---------- */
  function validateCourseForm(form) {
    form = form || {};
    var errors = [];
    var name = form.name != null ? String(form.name) : "";
    if (!name.trim()) errors.push("COURSE_NAME_EMPTY");
    var sections = form.sections || [];
    sections.forEach(function (sec, i) {
      if (sec && sec.startPeriod != null && sec.endPeriod != null && sec.startPeriod > sec.endPeriod) {
        errors.push("SECTION_START_AFTER_END:" + (i + 1));
      }
    });
    var weeks = form.weeks || [];
    if (weeks.length === 0) errors.push("WEEKS_EMPTY");
    return { ok: errors.length === 0, errors: errors };
  }

  /* ---------- computeInitialWeeks：由课程推导初始周次选择 ---------- */
  function computeInitialWeeks(courseOrNull, totalWeeks) {
    var weeks = [];
    var c = courseOrNull || null;
    totalWeeks = totalWeeks || 0;
    if (c && c.weeks && Array.isArray(c.weeks) && c.weeks.length > 0) {
      weeks = c.weeks.slice();
    } else if (c && c.weekType) {
      var i;
      if (c.weekType === "all") {
        for (i = 1; i <= totalWeeks; i++) weeks.push(i);
      } else if (c.weekType === "odd") {
        for (i = 1; i <= totalWeeks; i += 2) weeks.push(i);
      } else if (c.weekType === "even") {
        for (i = 2; i <= totalWeeks; i += 2) weeks.push(i);
      }
    } else {
      for (var j = 1; j <= totalWeeks; j++) weeks.push(j);
    }
    return weeks;
  }

  /* ---------- softDeleteCore：软删除纯状态变更 ---------- */
  function softDeleteCore(state, id) {
    state = state || {};
    var courses = state.courses || [];
    var c = null;
    for (var i = 0; i < courses.length; i++) {
      if (courses[i].id === id) { c = courses[i]; break; }
    }
    if (!c) return null;
    c._deleted = true;
    var entry = { course: c, at: (typeof Date !== "undefined" ? Date.now() : 0) };
    if (!state.deleted) state.deleted = [];
    state.deleted.push(entry);
    return { entry: entry, course: c };
  }

  /* ---------- undoDeleteCore：撤销软删除纯状态变更 ---------- */
  function undoDeleteCore(state, entry) {
    state = state || {};
    if (entry && entry.timer && typeof clearTimeout === "function") {
      try { clearTimeout(entry.timer); } catch (e) { /* 忽略 */ }
    }
    if (!state.deleted) return;
    var i = state.deleted.indexOf(entry);
    if (i >= 0) state.deleted.splice(i, 1);
    if (entry && entry.course) delete entry.course._deleted;
  }

  /* ---------- buildICSLines：构建 RFC5545 .ics 文本 ---------- */
  function icsDate(semMonday, weekday, period, isEnd, ctx) {
    var addDays = ctx.addDays, mondayOf = ctx.mondayOf, timeSlots = ctx.timeSlots;
    var d = addDays(mondayOf(semMonday), weekday - 1);
    var t = timeSlots[period - 1];
    var hm = isEnd ? t.end : t.start;
    var parts = hm.split(":");
    d.setHours(+parts[0], +parts[1], 0, 0);
    return d;
  }

  function buildICSLines(courses, opts, ctx) {
    opts = opts || {};
    ctx = ctx || {};
    var semesterStart = ctx.semesterStart;
    var getSections = ctx.getSections;
    var timeSlots = ctx.timeSlots;
    var icsDayCodes = ctx.icsDayCodes;
    var addDays = ctx.addDays;
    var mondayOf = ctx.mondayOf;
    var fmtICS = ctx.fmtICS;
    var escICS = ctx.escICS;

    var lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SmartTimetablePro//CN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"];
    var until = addDays(mondayOf(semesterStart), (opts.weeks || 0) * 7);
    var untilStr = fmtICS(until);
    courses.forEach(function (c) {
      var sections = getSections(c);
      sections.forEach(function (s, idx) {
        if (c.weeks && Array.isArray(c.weeks) && c.weeks.length > 0) {
          c.weeks.forEach(function (wn) {
            var start = icsDate(semesterStart, s.weekday, s.startPeriod, false, ctx);
            var end = icsDate(semesterStart, s.weekday, s.endPeriod, true, ctx);
            start = addDays(start, (wn - 1) * 7);
            end = addDays(end, (wn - 1) * 7);
            lines.push("BEGIN:VEVENT");
            lines.push("UID:" + c.id + "-week" + wn + "-" + idx + "@stp");
            lines.push("DTSTART:" + fmtICS(start));
            lines.push("DTEND:" + fmtICS(end));
            lines.push("SUMMARY:" + escICS(c.name));
            lines.push("LOCATION:" + escICS(s.location || ""));
            if (opts.notes) lines.push("DESCRIPTION:" + escICS("教师：" + (c.teacher || "") + "（第" + wn + "周）"));
            if (opts.reminder) lines.push("BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", "DESCRIPTION:" + escICS(c.name), "END:VALARM");
            lines.push("END:VEVENT");
          });
        } else {
          var interval = c.weekType === "all" ? 1 : 2;
          var start = icsDate(semesterStart, s.weekday, s.startPeriod, false, ctx);
          var end = icsDate(semesterStart, s.weekday, s.endPeriod, true, ctx);
          if (c.weekType === "even") { start = addDays(start, 7); end = addDays(end, 7); }
          var rrule = "FREQ=WEEKLY;INTERVAL=" + interval + ";BYDAY=" + icsDayCodes[s.weekday - 1] + ";UNTIL=" + untilStr;
          lines.push("BEGIN:VEVENT");
          lines.push("UID:" + c.id + "-" + (c.weekType || "all") + "-" + idx + "@stp");
          lines.push("DTSTART:" + fmtICS(start));
          lines.push("DTEND:" + fmtICS(end));
          lines.push("RRULE:" + rrule);
          lines.push("SUMMARY:" + escICS(c.name));
          lines.push("LOCATION:" + escICS(s.location || ""));
          if (opts.notes) lines.push("DESCRIPTION:" + escICS("教师：" + (c.teacher || "") + (c.weekType !== "all" ? "（" + (c.weekType === "odd" ? "单周" : "双周") + "）" : "")));
          if (opts.reminder) lines.push("BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", "DESCRIPTION:" + escICS(c.name), "END:VALARM");
          lines.push("END:VEVENT");
        }
      });
    });
    lines.push("END:VCALENDAR");
    return lines.join("\r\n");
  }

  /* ---------- splitIdlePlan：把所选空闲并集按标签数均匀切分为 n 段 ---------- */
  function splitIdlePlan(blocks, tags, opts) {
    opts = opts || {};
    var n = tags.length;
    if (n === 0) return { ok: false, reason: "NO_TAGS" };

    var minSeg = opts.minSeg != null ? opts.minSeg : 20;

    // 归一 blocks：用 opts.toMin 把字符串 "HH:MM" 转分钟（若 s/e 是字符串且 toMin 存在），
    // 过滤 e<=s 的非法块，按 s 升序排序（防御性）
    var norm = (blocks || []).map(function (b) {
      return {
        s: (typeof b.s === "string" && opts.toMin) ? opts.toMin(b.s) : b.s,
        e: (typeof b.e === "string" && opts.toMin) ? opts.toMin(b.e) : b.e
      };
    }).filter(function (b) { return b.e > b.s; })
      .sort(function (a, b) { return a.s - b.s; });

    if (norm.length === 0) {
      return { ok: false, reason: "INSUFFICIENT_TIME", needMinutes: n * minSeg, haveMinutes: 0 };
    }

    var total = norm.reduce(function (s, b) { return s + (b.e - b.s); }, 0);
    if (total < n * minSeg) {
      return { ok: false, reason: "INSUFFICIENT_TIME", needMinutes: n * minSeg, haveMinutes: total };
    }

    // 理想段长：整数分钟，余数补给前 rem 段，Σ lens === total
    var base = Math.floor(total / n), rem = total % n;
    var lens = [];
    for (var i = 0; i < n; i++) lens.push(base + (i < rem ? 1 : 0));

    // 块内顺序浇筑（保证每段完全落在某空闲块内，绝不跨课程间隙）
    var segments = [];
    var bi = 0, cur = norm[0].s, blkEnd = norm[0].e;
    for (var j = 0; j < n; j++) {
      var want = lens[j];
      while ((blkEnd - cur) < want && bi < norm.length - 1) {
        bi++; cur = norm[bi].s; blkEnd = norm[bi].e;
      }
      if ((blkEnd - cur) < want) {
        want = blkEnd - cur;   // 极端夹紧兜底：不跨间隙优先于绝对均分
      }
      var segS = cur, segE = cur + want;
      segments.push({ s: segS, e: segE, tag: tags[j] });
      cur = segE;
      if (cur >= blkEnd && bi < norm.length - 1) {
        bi++; cur = norm[bi].s; blkEnd = norm[bi].e;
      }
    }
    return { ok: true, segments: segments };
  }

  /* ---------- classifyTag：把单个待办标签归类到四个分类之一 ---------- */
  // 优先级 kg > kaoyan > study，其余（默认）归为 personal。
  // 统一转小写后用正则匹配（英文/拼音大小写不敏感，中文本身无大小写）。
  function classifyTag(text) {
    var s = String(text == null ? "" : text).toLowerCase();
    if (/考公|公务员|公考|行测|申论|国考|省考|选调|事业单位/.test(s)) return "kg";
    if (/考研|研究生|初试|复试|调剂|统考|英一|英二|数学[一二三]/.test(s)) return "kaoyan";
    if (/自习|复习|预习|作业|看书|阅读|学习|笔记|刷题|练习|课程|背诵|单词|错题/.test(s)) return "study";
    return "personal";
  }

  /* ---------- selectTags：按选中态集合过滤标签（保持原顺序） ---------- */
  // 纯函数等价实现：tags.filter(function(t){return selectedMap[t];})
  function selectTags(tags, selectedMap) {
    var out = [];
    for (var i = 0; i < (tags || []).length; i++) {
      if (selectedMap && selectedMap[tags[i]]) out.push(tags[i]);
    }
    return out;
  }

  /* ---------- planMatchesDate：判断某 self-plan 是否应显示在 targetDate 当天 ---------- */
  // item: {date, weekday, ...}
  // targetDateStr: fmtDateInput(targetDate)，如 "2026-07-19"
  // targetWeekday: 1-7
  // 规则：若 item.date 有值 → 严格按绝对日期匹配；
  //       若 item.date 为空（旧数据/用户留空）→ 退回按 weekday 匹配（保持“每周该星期都显示”的语义）
  function planMatchesDate(item, targetDateStr, targetWeekday) {
    if (!item) return false;
    if (item.date) return item.date === targetDateStr;
    return item.weekday === targetWeekday;
  }

  /* ---------- planTimeRange：返回 self-plan 的 {s, e} 分钟区间（精确时间优先，否则由节次推导） ---------- */
  // opts: { timeSlots, toMin }，toMin(hm)->minutes
  function planTimeRange(item, opts) {
    opts = opts || {};
    var ts = opts.timeSlots || [];
    var toMin = opts.toMin || function (hm) {
      var a = String(hm).split(":");
      return (+a[0]) * 60 + (+a[1]);
    };
    if (item && item.startMin != null && item.endMin != null) {
      return { s: item.startMin, e: item.endMin };
    }
    var sp = (item && item.startPeriod != null) ? item.startPeriod : 1;
    var ep = (item && item.endPeriod != null) ? item.endPeriod : sp;
    var s = ts[sp - 1] ? toMin(ts[sp - 1].start) : 0;
    var e = ts[ep - 1] ? toMin(ts[ep - 1].end) : s;
    return { s: s, e: e };
  }

  /* ---------- minutesToHM：分钟 -> "HH:MM" ---------- */
  function minutesToHM(m) {
    m = Math.max(0, Math.round(m));
    var h = Math.floor(m / 60), mm = m % 60;
    return (h < 10 ? "0" + h : h) + ":" + (mm < 10 ? "0" + mm : mm);
  }

  /* ---------- 导出 ---------- */
  var STPCore = {
    idleBlocks: idleBlocks,
    deriveWeekType: deriveWeekType,
    validateCourseForm: validateCourseForm,
    computeInitialWeeks: computeInitialWeeks,
    softDeleteCore: softDeleteCore,
    undoDeleteCore: undoDeleteCore,
    buildICSLines: buildICSLines,
    splitIdlePlan: splitIdlePlan,
    classifyTag: classifyTag,
    selectTags: selectTags,
    planMatchesDate: planMatchesDate,
    planTimeRange: planTimeRange,
    minutesToHM: minutesToHM
  };

  // Node：CommonJS 导出（供 tests/test_core.mjs 用 createRequire 引入）
  if (typeof module !== "undefined" && module.exports) {
    module.exports = STPCore;
  }
  // 浏览器：挂到 window.STPCore
  if (typeof global !== "undefined") {
    global.STPCore = STPCore;
  }
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
