"""Actions schedule/tasks tools tests (with injected providers)."""
from datetime import date, datetime

import pytest

from pet import actions
from pet.schedule import Schedule, import_strongzhi
from pet.tasks import Tasks

MINI_KB = {"kbList": [{"kcmc": "高数", "xqj": "1", "jc": "1-2节",
                       "zcd": "1-14周", "cdmc": "3教201", "xm": "张",
                       "xqmc": "x", "pkbj": "1", "xkbz": " "}]}


@pytest.fixture()
def providers(tmp_path):
    sched = Schedule(path=str(tmp_path / "s.json"))
    courses, _, _ = import_strongzhi(MINI_KB, date(2026, 9, 7))
    sched.save(term_start=date.today(), courses=courses)
    tasks = Tasks(path=str(tmp_path / "t.json"))
    actions.set_schedule_provider(lambda: sched)
    actions.set_tasks_provider(lambda: tasks)
    yield sched, tasks
    actions.set_schedule_provider(None)
    actions.set_tasks_provider(None)


class TestScheduleTools:
    def test_query_schedule_today(self, providers):
        # 迷你课表只有周一的高数；"今天"取决于真实星期，故只断言结构
        out = actions.query_schedule("today")
        assert out.startswith("今天") and ("节课" in out or "没有课" in out)

    def test_query_schedule_week(self, providers):
        assert "高数" in actions.query_schedule("week")

    def test_query_schedule_next(self, providers):
        out = actions.query_schedule("next")
        assert out and ("高数" in out or "没有剩下的课" in out)

    def test_query_schedule_no_data(self):
        actions.set_schedule_provider(lambda: None)
        assert "还没有导入课表" in actions.query_schedule("today")

    def test_run_action_dispatch(self, providers):
        out = actions.run_action("query_schedule", {"scope": "week"})
        assert "高数" in out


class TestTaskTools:
    def test_add_task_parses_natural_language(self, providers):
        sched, tasks = providers
        out = actions.add_task("高数作业", "明天", course="高等数学")
        assert "已添加作业" in out and len(tasks.items) == 1

    def test_add_task_exam(self, providers):
        sched, tasks = providers
        actions.add_task("期末考试", "9月20日", kind="exam")
        assert tasks.items[0].kind == "exam"

    def test_add_task_bad_date(self, providers):
        sched, tasks = providers
        out = actions.add_task("作业", "不知道什么时候")
        assert "没能理解" in out and len(tasks.items) == 0

    def test_query_tasks(self, providers):
        sched, tasks = providers
        actions.add_task("高数作业", "明天")
        assert "高数作业" in actions.query_tasks()

    def test_query_tasks_empty(self, providers):
        sched, tasks = providers
        assert "没有待办" in actions.query_tasks()


class TestTodaySummary:
    def test_summary_includes_course(self, providers):
        out = actions.today_summary()
        assert ("今天" in out and ("节课" in out or "没有课" in out))

    def test_summary_includes_tasks(self, providers):
        sched, tasks = providers
        actions.add_task("高数作业", "明天", course="高等数学")
        actions.add_task("期末考试", "2026-12-25", kind="exam")
        out = actions.today_summary()
        assert "高数作业" in out and "期末考试" in out

    def test_summary_empty(self):
        actions.set_schedule_provider(lambda: None)
        actions.set_tasks_provider(lambda: None)
        assert "没有安排" in actions.today_summary()


class TestToolsSchema:
    def test_new_tools_in_schema(self):
        names = [t["function"]["name"] for t in actions.TOOLS]
        assert "query_schedule" in names
        assert "query_tasks" in names
        assert "add_task" in names
        assert "today_summary" in names
        assert "system_status" in names
        assert "type_text" in names
        assert "clipboard" in names
        assert "window_control" in names

    def test_all_handlers_registered(self):
        for t in actions.TOOLS:
            assert t["function"]["name"] in actions._HANDLERS


class TestComputerControl:
    def test_open_app_unknown(self):
        out = actions.open_app("不存在的程序xyz")
        assert "我只能打开" in out

    def test_custom_apps_loaded(self, tmp_path, monkeypatch):
        p = tmp_path / "apps.json"
        p.write_text('{"我的程序": "C:\\\\no\\\\such\\\\app.exe"}', encoding="utf-8")
        monkeypatch.setenv("PET_APPS_FILE", str(p))
        out = actions.open_app("我的程序")
        # 路径不存在 -> 明确失败（识别到了但打不开），而不是"不认识"
        assert "没找到" in out

    def test_system_status_shape(self):
        out = actions.system_status()
        assert isinstance(out, str) and "前台窗口" in out

    def test_type_text_empty(self):
        assert "想让我输入" in actions.type_text("")

    def test_type_text_too_long(self):
        assert "最多输入" in actions.type_text("x" * 501)

    def test_clipboard_bad_action(self):
        assert "只支持" in actions.clipboard("paste")

    def test_clipboard_get_is_str(self):
        out = actions.clipboard("get")
        assert isinstance(out, str)

    def test_window_control_bad_action(self):
        out = actions.window_control("explode")
        assert "只支持" in out

    def test_window_control_no_name(self):
        out = actions.window_control("minimize")
        assert "没找到" in out or "先列出窗口" in out

    def test_window_control_list(self):
        out = actions.window_control("list")
        assert isinstance(out, str) and "窗口" in out
