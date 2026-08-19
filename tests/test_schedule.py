"""Schedule module tests: week/section parsing, import, queries, persistence."""
import json
from datetime import date, datetime

import pytest

from pet.schedule import (
    Course, Schedule, import_strongzhi, parse_sections, parse_weeks)


class TestParsing:
    def test_parse_weeks_basic(self):
        assert parse_weeks("1-14周") == (1, 14, "all")
        assert parse_weeks("3-17周") == (3, 17, "all")
        assert parse_weeks("14-15周") == (14, 15, "all")

    def test_parse_weeks_parity(self):
        assert parse_weeks("8-12周(双)") == (8, 12, "even")
        assert parse_weeks("1-16周(单)") == (1, 16, "odd")

    def test_parse_weeks_invalid(self):
        assert parse_weeks("无") is None
        assert parse_weeks("") is None

    def test_parse_sections(self):
        assert parse_sections("1-2节") == (1, 2)
        assert parse_sections("11-13") == (11, 13)
        assert parse_sections("x") is None

    def test_room_from_xkbz(self):
        rec = {"cdmc": "未排地点",
               "xkbz": "8,10,12周日2-5节A204"}
        from pet.schedule import _room_of
        assert _room_of(rec) == "A204"
        assert _room_of({"cdmc": "3区2-217", "xkbz": " "}) == "3区2-217"


MINI_KB = {
    "xsxx": {"XNMC": "2026-2027", "XQMMC": "1"},
    "kbList": [
        {"kcmc": "高数", "xqj": "1", "jc": "1-2节", "zcd": "1-14周",
         "cdmc": "3教201", "xm": "张", "xqmc": "信息学部", "pkbj": "1",
         "xkbz": " "},
        {"kcmc": "实验课", "xqj": "7", "jc": "2-5节", "zcd": "8-12周(双)",
         "cdmc": "未排地点", "xm": "李", "xqmc": "信息学部", "pkbj": "0",
         "xkbz": "8,10,12周日2-5节A204"},
    ],
    "sjkList": [{"kcmc": "网课", "jsxm": "王", "qsjsz": "1-16周"}],
}


class TestImport:
    def test_import_strongzhi(self):
        courses, notes, skipped = import_strongzhi(MINI_KB, date(2026, 9, 7))
        assert len(courses) == 2
        assert len(notes) == 1
        assert not skipped
        lab = courses[1]
        assert lab.parity == "even" and lab.room == "A204"

    def test_import_skips_bad_records(self):
        raw = {"kbList": [{"kcmc": "坏数据", "xqj": "9", "jc": "1-2",
                           "zcd": "1-14周"}]}
        courses, notes, skipped = import_strongzhi(raw, date(2026, 9, 7))
        assert courses == [] and len(skipped) == 1


class TestCourse:
    def test_active_on_parity(self):
        c = Course("实验", 7, 2, 5, 8, 12, "even")
        assert not c.active_on(9)
        assert c.active_on(10)
        c2 = Course("课", 1, 1, 2, 1, 16, "odd")
        assert c2.active_on(3) and not c2.active_on(2)

    def test_start_time_out_of_range(self):
        c = Course("课", 1, 1, 2, 1, 14, "all")
        assert c.start_time(20, {"1": "08:00"}) is None


class TestSchedule:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "schedule.json"
        s = Schedule(path=str(p))
        courses, notes, _ = import_strongzhi(MINI_KB, date(2026, 9, 7))
        assert s.save(term="2026-2027-1", term_start=date(2026, 9, 7),
                      courses=courses, notes=notes)
        s2 = Schedule(path=str(p))
        assert len(s2.courses) == 2
        assert s2.term_start == date(2026, 9, 7)

    def test_week_no(self):
        s = Schedule(path=str(__import__("tempfile").mkstemp()[1]))
        s.save(term_start=date(2026, 9, 7))
        assert s.week_no(date(2026, 9, 7)) == 1
        assert s.week_no(date(2026, 9, 14)) == 2

    def test_next_class(self):
        import tempfile
        s = Schedule(path=tempfile.mkstemp()[1])
        courses, _, _ = import_strongzhi(MINI_KB, date(2026, 9, 7))
        s.save(term_start=date(2026, 9, 7), courses=courses)
        now = datetime(2026, 9, 7, 7, 0)   # 周一 07:00，第一节课 08:00
        nxt = s.next_class(now=now)
        assert nxt is not None
        c, _, _, start = nxt
        assert c.name == "高数" and start.hour == 8

    def test_dump_text_marks_off_weeks(self):
        import tempfile
        s = Schedule(path=tempfile.mkstemp()[1])
        courses, _, _ = import_strongzhi(MINI_KB, date(2026, 9, 7))
        s.save(term_start=date(2026, 9, 7), courses=courses)
        text = s.dump_text(week_no=9)
        assert "高数" in text
        assert "本周不上" in text or "实验" in text  # 第9周单周，实验(双)不上
