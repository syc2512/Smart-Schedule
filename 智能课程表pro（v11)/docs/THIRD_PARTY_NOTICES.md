# Third-Party Notices

## 拾光课程表 / shiguangschedule

- Upstream: https://github.com/XingHeYuZhuan/shiguangschedule
- License: Apache License 2.0
- Referenced for product research and architectural comparison only.

The Smart Timetable Pro implementation is written in TypeScript and Python. Its
React components, FastAPI services, JSON adapter and schedule layout engine are
independent implementations. No Kotlin source files, brand assets or application
icons from the upstream project are included in this repository.

The optional JSON compatibility import follows the publicly exposed field names
of the upstream data format so users can migrate their own timetable data. If
future changes directly copy upstream source code, the Apache 2.0 copyright and
license notice must be added to the specific files and this document must state
the modifications.

## 课表转换器 / calender-transporter

- Upstream author: Xue Zicheng
- License: MIT
- Referenced for deterministic Excel timetable parsing and time-slot conventions.

The tabular importer in this repository is an independent Python implementation
with upload limits, header detection, structured warnings, preview confirmation,
saved import profiles and multi-campus time rules. The upstream command-line
program is not included in the build.
