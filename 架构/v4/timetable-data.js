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
    "indexedDBStore": "courses"
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

  "seedCourses": [
    { "name": "高等数学",       "teacher": "张老师", "location": "教三-201",       "weekday": 1, "startPeriod": 1, "endPeriod": 2,  "weekType": "all",  "colorIndex": 2 },
    { "name": "大学英语",       "teacher": "李老师", "location": "外语楼-305",     "weekday": 1, "startPeriod": 3, "endPeriod": 4,  "weekType": "all",  "colorIndex": 8 },
    { "name": "程序设计基础",   "teacher": "王老师", "location": "计算机楼-401",   "weekday": 1, "startPeriod": 5, "endPeriod": 6,  "weekType": "all",  "colorIndex": 6 },
    { "name": "体育",           "teacher": "赵老师", "location": "体育馆",         "weekday": 1, "startPeriod": 9, "endPeriod": 10, "weekType": "all",  "colorIndex": 5 },
    { "name": "线性代数",       "teacher": "陈老师", "location": "教二-102",       "weekday": 2, "startPeriod": 1, "endPeriod": 2,  "weekType": "all",  "colorIndex": 4 },
    { "name": "数据结构",       "teacher": "刘老师", "location": "计算机楼-305",   "weekday": 2, "startPeriod": 3, "endPeriod": 4,  "weekType": "all",  "colorIndex": 1 },
    { "name": "离散数学",       "teacher": "孙老师", "location": "教三-208",       "weekday": 2, "startPeriod": 5, "endPeriod": 6,  "weekType": "odd",  "colorIndex": 9 },
    { "name": "创新创业讲座",   "teacher": "周老师", "location": "食堂三楼",       "weekday": 2, "startPeriod": 7, "endPeriod": 8,  "weekType": "even", "colorIndex": 3 },
    { "name": "高等数学",       "teacher": "张老师", "location": "教三-201",       "weekday": 3, "startPeriod": 1, "endPeriod": 2,  "weekType": "all",  "colorIndex": 2 },
    { "name": "大学物理",       "teacher": "吴老师", "location": "物理楼-110",     "weekday": 3, "startPeriod": 3, "endPeriod": 4,  "weekType": "all",  "colorIndex": 7 },
    { "name": "程序设计基础",   "teacher": "王老师", "location": "计算机楼-401",   "weekday": 3, "startPeriod": 5, "endPeriod": 6,  "weekType": "all",  "colorIndex": 6 },
    { "name": "英语口语",       "teacher": "李老师", "location": "外语楼-401",     "weekday": 3, "startPeriod": 9, "endPeriod": 10, "weekType": "odd",  "colorIndex": 11 },
    { "name": "线性代数",       "teacher": "陈老师", "location": "教二-102",       "weekday": 4, "startPeriod": 1, "endPeriod": 2,  "weekType": "all",  "colorIndex": 4 },
    { "name": "操作系统",       "teacher": "郑老师", "location": "计算机楼-302",   "weekday": 4, "startPeriod": 3, "endPeriod": 4,  "weekType": "all",  "colorIndex": 10 },
    { "name": "计算机网络",     "teacher": "冯老师", "location": "计算机楼-305",   "weekday": 4, "startPeriod": 5, "endPeriod": 6,  "weekType": "even", "colorIndex": 12 },
    { "name": "学术报告",       "teacher": "黄老师", "location": "图书馆报告厅",   "weekday": 4, "startPeriod": 3, "endPeriod": 4,  "weekType": "all",  "colorIndex": 12 },
    { "name": "数据结构",       "teacher": "刘老师", "location": "计算机楼-305",   "weekday": 4, "startPeriod": 7, "endPeriod": 8,  "weekType": "all",  "colorIndex": 1 },
    { "name": "高等数学",       "teacher": "张老师", "location": "教三-201",       "weekday": 5, "startPeriod": 1, "endPeriod": 2,  "weekType": "all",  "colorIndex": 2 },
    { "name": "马克思主义原理", "teacher": "钱老师", "location": "教一-501",       "weekday": 5, "startPeriod": 3, "endPeriod": 4,  "weekType": "all",  "colorIndex": 3 },
    { "name": "数据库系统",     "teacher": "王老师", "location": "计算机楼-402",   "weekday": 5, "startPeriod": 5, "endPeriod": 6,  "weekType": "all",  "colorIndex": 6 },
    { "name": "社团活动",       "teacher": "孙老师", "location": "学生中心",       "weekday": 5, "startPeriod": 9, "endPeriod": 10, "weekType": "odd",  "colorIndex": 11 },
    { "name": "考研英语",       "teacher": "自习",   "location": "图书馆",         "weekday": 6, "startPeriod": 1, "endPeriod": 3,  "weekType": "all",  "colorIndex": 8 },
    { "name": "考研数学",       "teacher": "自习",   "location": "图书馆",         "weekday": 6, "startPeriod": 5, "endPeriod": 7,  "weekType": "all",  "colorIndex": 4 }
  ],

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

  "exportOptions": [
    { "value": "reminder", "label": "课前 15 分钟提醒" },
    { "value": "notes",    "label": "含教师备注" },
    { "value": "both",     "label": "提醒+备注" }
  ],

  "ai": {
    "defaultBaseUrl": "https://api.openai.com/v1",
    "defaultModel": "gpt-4o-mini",
    "timeouts": {
      "text": 15000,
      "image": 20000,
      "file": 30000
    },
    "prompts": {
      "parseText":  "你是课程表解析助手。从文本中提取课程，返回 JSON 数组。每门课程字段：name(课程名),teacher(教师),location(地点),weekday(1-7,周一至周日),startPeriod(起始节次1-12),endPeriod(结束节次1-12),weekType('all'|'odd'|'even'),colorIndex(0-11,可空)。仅返回 JSON，不要解释。",
      "parseImage": "从课程表截图提取课程，返回 JSON 数组。字段：name,teacher,location,weekday(1-7),startPeriod,endPeriod,weekType('all'|'odd'|'even'),colorIndex(0-11)。仅返回 JSON。",
      "parseFile":  "从文件中提取课程信息，返回 JSON 数组。字段：name,teacher,location,weekday(1-7),startPeriod,endPeriod,weekType('all'|'odd'|'even'),colorIndex(0-11)。仅返回 JSON。"
    }
  }
};
