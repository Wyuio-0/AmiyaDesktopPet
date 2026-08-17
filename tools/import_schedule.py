"""命令行导入强智课表 JSON -> %APPDATA%\\AmiyaPet\\schedule.json

用法（把从教务系统 Network 复制的 JSON 保存为文件后）：
    python tools/import_schedule.py 课表.json
    python tools/import_schedule.py 课表.json --term-start 2026-08-31

--term-start 是第 1 周周一的日期；不传则默认"今天所在周的周一"，
导入后也可以直接编辑 schedule.json 里的 term_start / sections 修正。
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pet.schedule import Schedule, import_strongzhi, _data_path, _raw_path


def main():
    ap = argparse.ArgumentParser(description="导入强智课表 JSON")
    ap.add_argument("json_file", help="从教务系统复制的课表 JSON 文件")
    ap.add_argument("--term-start", default=None,
                    help="第 1 周周一的日期 YYYY-MM-DD（默认今天所在周的周一）")
    args = ap.parse_args()

    try:
        with open(args.json_file, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        sys.exit("读取失败：%s" % e)

    if not raw.get("kbList") and not raw.get("sjkList"):
        sys.exit("这不是强智课表 JSON（缺少 kbList 字段），请检查复制的数据。")

    if args.term_start:
        try:
            term_start = date.fromisoformat(args.term_start)
        except ValueError:
            sys.exit("--term-start 格式应为 YYYY-MM-DD")
    else:
        term_start = date.today() - timedelta(days=date.today().isoweekday() - 1)

    courses, notes, skipped = import_strongzhi(raw, term_start)
    if not courses:
        sys.exit("没有解析出任何课程，请检查 JSON 内容。")

    xs = raw.get("xsxx", {}) or {}
    term = "%s-第%s学期" % (xs.get("XNMC", ""), xs.get("XQMMC", ""))
    sched = Schedule()
    if not sched.save(term=term, term_start=term_start,
                      courses=courses, notes=notes):
        sys.exit("写入 %s 失败" % _data_path())

    # 原始 JSON 留档，便于每学期重新导入/核对。
    try:
        with open(_raw_path(), "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    print("课表导入完成：")
    print("  课程 %d 门，无时间课 %d 条，跳过 %d 条" % (len(courses), len(notes), len(skipped)))
    print("  学期：%s   第 1 周周一：%s" % (term, term_start.isoformat()))
    print("  保存到：%s" % _data_path())
    if skipped:
        print("  注意：以下条目未能解析：%s" % skipped)
    print()
    print("如需调整上课时间表或提醒提前量，编辑 schedule.json 的 sections / "
          "remind_minutes 字段后重启桌宠。")


if __name__ == "__main__":
    main()
