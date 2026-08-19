"""Tasks module tests: Chinese datetime parsing, persistence, reminder window."""
from datetime import date, datetime, timedelta

import pytest

from pet.tasks import Tasks, parse_datetime

NOW = datetime(2026, 9, 7, 10, 0)   # 周一


class TestParseDatetime:
    def test_relative(self):
        assert parse_datetime("今天23:59", NOW) == (datetime(2026, 9, 7, 23, 59), True)
        assert parse_datetime("明天", NOW) == (datetime(2026, 9, 8, 18, 0), True)
        assert parse_datetime("后天", NOW) == (datetime(2026, 9, 9, 18, 0), True)

    def test_weekday(self):
        assert parse_datetime("周五前交高数作业", NOW) == (
            datetime(2026, 9, 11, 18, 0), True)
        assert parse_datetime("下周一", NOW) == (datetime(2026, 9, 14, 18, 0), True)

    def test_absolute(self):
        assert parse_datetime("9月20日", NOW) == (datetime(2026, 9, 20, 18, 0), True)
        assert parse_datetime("2026年12月25日 14:00", NOW) == (
            datetime(2026, 12, 25, 14, 0), True)
        assert parse_datetime("2026-12-25", NOW) == (datetime(2026, 12, 25, 18, 0), True)

    def test_time_forms(self):
        assert parse_datetime("今天9点", NOW) == (datetime(2026, 9, 7, 9, 0), True)
        assert parse_datetime("今天9点半", NOW) == (datetime(2026, 9, 7, 9, 30), True)
        assert parse_datetime("今天9点30分", NOW) == (datetime(2026, 9, 7, 9, 30), True)

    def test_unparsable(self):
        dt, ok = parse_datetime("交作业", NOW)
        assert dt is None and not ok
        dt, ok = parse_datetime("", NOW)
        assert dt is None and not ok


class TestTasks:
    def test_add_remove_done(self, tmp_path):
        ts = Tasks(path=str(tmp_path / "tasks.json"))
        ts.add("高数作业", "homework", datetime(2026, 9, 10, 23, 59),
               course="高等数学", remind_min=1440)
        assert len(ts.items) == 1
        tid = ts.items[0].id
        ts.set_done(tid)
        assert ts.items[0].done
        ts.remove(tid)
        assert not ts.items

    def test_persistence(self, tmp_path):
        p = tmp_path / "tasks.json"
        ts = Tasks(path=str(p))
        ts.add("考试", "exam", datetime(2026, 12, 25, 14, 0), remind_min=10080)
        ts2 = Tasks(path=str(p))
        assert len(ts2.items) == 1 and ts2.items[0].kind == "exam"

    def test_due_soon_window(self, tmp_path):
        ts = Tasks(path=str(tmp_path / "tasks.json"))
        t = ts.add("作业", "homework", datetime(2026, 9, 8, 23, 59),
                   remind_min=60 * 24)
        assert not ts.due_soon(now=NOW)                    # 未进入窗口
        soon = ts.due_soon(now=NOW + timedelta(hours=14))  # 窗口内
        assert any(x.id == t.id for x in soon)

    def test_upcoming_sorted_excludes_done(self, tmp_path):
        ts = Tasks(path=str(tmp_path / "tasks.json"))
        a = ts.add("早", "homework", datetime(2026, 9, 8, 10, 0))
        b = ts.add("晚", "homework", datetime(2026, 9, 9, 10, 0))
        ts.set_done(b.id)
        up = ts.upcoming()
        assert [t.id for t in up] == [a.id]

    def test_dump_text(self, tmp_path):
        ts = Tasks(path=str(tmp_path / "tasks.json"))
        ts.add("高数作业", "homework", datetime(2026, 9, 10, 23, 59),
               course="高等数学")
        text = ts.dump_text()
        assert "高数作业" in text
