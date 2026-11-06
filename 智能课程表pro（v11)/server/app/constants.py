"""Shared timetable configuration."""

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

TIME_SLOTS = [
    {"period": 1, "start": "08:00", "end": "08:45"},
    {"period": 2, "start": "08:55", "end": "09:40"},
    {"period": 3, "start": "10:00", "end": "10:45"},
    {"period": 4, "start": "10:55", "end": "11:40"},
    {"period": 5, "start": "14:00", "end": "14:45"},
    {"period": 6, "start": "14:55", "end": "15:40"},
    {"period": 7, "start": "16:00", "end": "16:45"},
    {"period": 8, "start": "16:55", "end": "17:40"},
    {"period": 9, "start": "19:00", "end": "19:45"},
    {"period": 10, "start": "19:55", "end": "20:40"},
    {"period": 11, "start": "20:50", "end": "21:35"},
    {"period": 12, "start": "21:45", "end": "22:30"},
]

COLOR_PALETTE = [
    {"bg": "#fee2e2", "stripe": "#dc2626"},
    {"bg": "#ffedd5", "stripe": "#ea580c"},
    {"bg": "#fef3c7", "stripe": "#d97706"},
    {"bg": "#ecfccb", "stripe": "#65a30d"},
    {"bg": "#dcfce7", "stripe": "#16a34a"},
    {"bg": "#ccfbf1", "stripe": "#0d9488"},
    {"bg": "#cffafe", "stripe": "#0891b2"},
    {"bg": "#dbeafe", "stripe": "#2563eb"},
    {"bg": "#e0e7ff", "stripe": "#4f46e5"},
    {"bg": "#ede9fe", "stripe": "#7c3aed"},
    {"bg": "#fce7f3", "stripe": "#db2777"},
    {"bg": "#ffe4e6", "stripe": "#e11d48"},
]

TOTAL_WEEKS = 18
DAY_START_MINUTES = 8 * 60
DAY_END_MINUTES = 22 * 60 + 30
