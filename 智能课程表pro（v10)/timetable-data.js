/* ============================================================
   智能课程表 Pro — 数据文件
   通过 <script src> 加载，file:// 和 http:// 协议均可使用
   ============================================================ */
window.TIMETABLE_DATA = {
  "meta": {
    "version": "1.0",
    "appName": "智能课程表 Pro",
    "appSubtitle": "Smart Timetable Pro"
  },

  "layout": {
    "rowHeight": 54,
    "dayStartMinutes": 420,
    "dayEndMinutes": 1350,
    "hourHeight": 52,
    "totalWeeks": 18
  },

  "storage": {
    "coursesKey": "stp_courses_v1",
    "settingsKey": "stp_settings_v1",
    "indexedDBName": "stp_db",
    "indexedDBStore": "courses",
    "selfPlansKey": "stp_selfplans_v1"
  },

  "timeSlots": [
    { "period": 1,  "start": "08:00", "end": "08:45" },
    { "period": 2,  "start": "08:55", "end": "09:40" },
    { "period": 3,  "start": "10:00", "end": "10:45" },
    { "period": 4,  "start": "10:55", "end": "11:40" },
    { "period": 5,  "start": "14:00", "end": "14:45" },
    { "period": 6,  "start": "14:55", "end": "15:40" },
    { "period": 7,  "start": "16:00", "end": "16:45" },
    { "period": 8,  "start": "16:55", "end": "17:40" },
    { "period": 9,  "start": "19:00", "end": "19:45" },
    { "period": 10, "start": "19:55", "end": "20:40" },
    { "period": 11, "start": "20:50", "end": "21:35" },
    { "period": 12, "start": "21:45", "end": "22:30" }
  ],

  "colorPalette": [
    { "bg": "#fee2e2", "stripe": "#dc2626" },
    { "bg": "#ffedd5", "stripe": "#ea580c" },
    { "bg": "#fef3c7", "stripe": "#d97706" },
    { "bg": "#ecfccb", "stripe": "#65a30d" },
    { "bg": "#dcfce7", "stripe": "#16a34a" },
    { "bg": "#ccfbf1", "stripe": "#0d9488" },
    { "bg": "#cffafe", "stripe": "#0891b2" },
    { "bg": "#dbeafe", "stripe": "#2563eb" },
    { "bg": "#e0e7ff", "stripe": "#4f46e5" },
    { "bg": "#ede9fe", "stripe": "#7c3aed" },
    { "bg": "#fce7f3", "stripe": "#db2777" },
    { "bg": "#ffe4e6", "stripe": "#e11d48" }
  ],

  "weekdays": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
  "icsDayCodes": ["MO", "TU", "WE", "TH", "FR", "SA", "SU"],

  "weekTypes": [
    { "value": "all",  "label": "每周" },
    { "value": "odd",  "label": "单周" },
    { "value": "even", "label": "双周" }
  ],

  // 模拟课程数据来自 test_data.js（window.STP_MOCK_DATA.mockCourses），
  // 对应未来后端 GET /api/courses 的返回值。后端就绪后在此替换为真实接口数据。
  "seedCourses": (typeof window !== "undefined" && window.STP_MOCK_DATA ? window.STP_MOCK_DATA.mockCourses : []),

  "planner": {
    "goals": [
      { "value": "study",  "label": "日常自习" },
      { "value": "kaoyan", "label": "考研冲刺" },
      { "value": "kg",     "label": "考公备考" }
    ],
    "templates": {
      "study":  ["课后复习", "预习明日课程", "整理笔记", "阅读专业书", "完成作业", "小组讨论"],
      "kaoyan": ["数学刷题", "英语阅读+单词", "专业课背诵", "错题复盘", "政治背诵", "模拟考试"],
      "kg":     ["行测刷题", "申论写作", "时政背诵", "模考复盘", "常识积累", "面试准备"]
    }
  },

  // 空闲规划助手的标签自动分类（与 planner 同级）
  "idleCategories": [
    { "value": "personal", "label": "个人事务" },
    { "value": "kg",       "label": "考公" },
    { "value": "kaoyan",   "label": "考研" },
    { "value": "study",    "label": "自习" }
  ],

  "exportOptions": [
    { "value": "reminder", "label": "课前 15 分钟提醒" },
    { "value": "notes",    "label": "含教师备注" },
    { "value": "both",     "label": "提醒+备注" }
  ],

};
