/* ============================================================
   临时模拟数据文件 (test_data.js)
   ------------------------------------------------------------
   ⚠️ 本文件仅用于前端开发 / 演示，存放「本应由后端 API 返回、
      但目前硬编码在前端」的模拟数据（示例课程列表）。

   后端接口开发完成后，请按以下步骤切换为真实数据：
     1. 删除本文件 test_data.js；
     2. 在 timetable-data.js 中，将 seedCourses 对
        window.STP_MOCK_DATA.mockCourses 的引用，替换为真实
        接口调用，例如：
          // seedCourses: (await fetch('/api/courses').then(r => r.json())),
        或把数据获取上移到应用启动逻辑里再做赋值；
     3. 只要后端返回的数据结构与下方 mockCourses 保持一致
        （字段：name/teacher/location/weekday/startPeriod/
         endPeriod/weekType/colorIndex），前端渲染逻辑无需改动。

   命名约定：导出名 mockCourses 刻意对齐「未来 GET /api/courses
   的返回值」，便于直接替换、降低切换成本。
   ============================================================ */

// 模拟「我的课程」列表 —— 对应未来 GET /api/courses 的返回值
const mockCourses = [
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
];

/* ------------------------------------------------------------
   导出兼容层（无构建步骤也能跑，未来接打包工具可平滑切换）
   ------------------------------------------------------------ */

// 1) 浏览器全局：timetable-data.js 通过 <script src> 读取它
//    （保持 file:// 直接打开可用，无需 dev server）
if (typeof window !== "undefined") {
  window.STP_MOCK_DATA = { mockCourses: mockCourses };
}

// 2) CommonJS：Node / 单测 / 构建工具场景下的模块化导入
//    （对应需求中的 module.exports 选项）
if (typeof module !== "undefined" && module.exports) {
  module.exports = { mockCourses: mockCourses };
}

// 3) 未来若引入打包工具并改用 ES Module，可删除上方两段，改为：
//      export { mockCourses };
//    并在 timetable-data.js 顶部写：
//      import { mockCourses } from './test_data.js';
//    同时把本文件 <script src> 改为 type="module"（需经 http(s) 加载）。
