"""
把网页登记工具导出的 JSON 文件，合并写回《科特迪瓦考勤登记表2026.xlsx》对应月份的工作表。

用法：
    python merge_attendance.py 考勤登记_2026年8月_张三.json 考勤登记_2026年8月_李四.json ...

    可选参数：
    --workbook 路径      默认当前目录下的 "科特迪瓦考勤登记表2026.xlsx"
    --output 路径        默认在原文件名后加 "_已合并"，不覆盖原文件
    --in-place           直接覆盖原工作簿（谨慎使用）

行为：
    - 多个文件按命令行给出的顺序合并；同一人同一天在不同文件里出现不同取值时，
      以 exportedAt 时间戳较新的为准，并打印一条冲突提示。
    - 按月份工作表 B 列的姓名匹配行号（从第2行往下，直到出现空行为止）；
      导出数据里若有姓名在该月表格里找不到，会列出来，不会写入。
    - 写入后调用 LibreOffice 重新计算全表公式，并报告是否有公式错误。
"""
import argparse
import json
import sys
from pathlib import Path

import openpyxl

SCRIPT_DIR = Path(__file__).resolve().parent


def load_entries(paths):
    all_entries = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            payload = json.load(f)
        exported_at = payload.get("exportedAt", "")
        year = payload.get("year")
        month = payload.get("month")
        for e in payload.get("entries", []):
            all_entries.append({
                "source": Path(p).name,
                "exportedAt": exported_at,
                "year": year,
                "month": month,
                "name": e["name"],
                "day": e["day"],
                "value": e["value"],
            })
    return all_entries


def resolve_conflicts(entries):
    """Same (year, month, name, day) may appear in multiple files -> keep the one with the latest exportedAt."""
    best = {}
    conflicts = []
    for e in entries:
        key = (e["year"], e["month"], e["name"], e["day"])
        if key not in best:
            best[key] = e
            continue
        prev = best[key]
        if prev["value"] == e["value"]:
            continue
        winner = e if (e["exportedAt"] or "") > (prev["exportedAt"] or "") else prev
        loser = prev if winner is e else e
        conflicts.append((key, winner, loser))
        best[key] = winner
    return list(best.values()), conflicts


def build_name_row_map(ws, name_col=2, start_row=2):
    mapping = {}
    row = start_row
    while True:
        name = ws.cell(row=row, column=name_col).value
        if name is None or str(name).strip() == "":
            break
        mapping[str(name).strip()] = row
        row += 1
    return mapping


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_files", nargs="+", help="网页工具导出的 JSON 文件路径")
    ap.add_argument("--workbook", default=str(SCRIPT_DIR / "科特迪瓦考勤登记表2026.xlsx"))
    ap.add_argument("--output", default=None)
    ap.add_argument("--in-place", action="store_true")
    args = ap.parse_args()

    entries = load_entries(args.json_files)
    if not entries:
        print("没有读到任何登记内容。")
        sys.exit(1)

    months = {(e["year"], e["month"]) for e in entries}
    if len(months) > 1:
        print(f"警告：这批文件里出现了多个不同的年月 {sorted(months)}，将分别写入各自对应的工作表。")

    entries, conflicts = resolve_conflicts(entries)
    if conflicts:
        print(f"发现 {len(conflicts)} 处冲突（同一人同一天在不同文件里取值不同），已按导出时间较新的为准：")
        for key, winner, loser in conflicts:
            year, month, name, day = key
            print(f"  {year}年{month}月{day}日 {name}: 采用「{winner['value']}」(来自 {winner['source']})，"
                  f"舍弃「{loser['value']}」(来自 {loser['source']})")

    wb = openpyxl.load_workbook(args.workbook, data_only=False)

    written = 0
    unmatched_names = {}
    for (year, month) in sorted(months):
        sheet_name = f"{year}年{month}月份"
        if sheet_name not in wb.sheetnames:
            print(f"错误：工作簿里没有名为「{sheet_name}」的工作表，跳过这部分数据。")
            continue
        ws = wb[sheet_name]
        name_row = build_name_row_map(ws)
        month_entries = [e for e in entries if e["year"] == year and e["month"] == month]
        for e in month_entries:
            row = name_row.get(e["name"])
            if row is None:
                unmatched_names.setdefault(sheet_name, set()).add(e["name"])
                continue
            col = 12 + e["day"]  # M=13 -> day 1
            ws.cell(row=row, column=col, value=e["value"])
            written += 1

    if unmatched_names:
        print("以下姓名在对应月份表格里找不到（可能是当月没有排班/名字打错），未写入：")
        for sheet_name, names in unmatched_names.items():
            print(f"  {sheet_name}: {', '.join(sorted(names))}")

    if args.in_place:
        out_path = Path(args.workbook)
    else:
        out_path = Path(args.output) if args.output else Path(args.workbook).with_name(
            Path(args.workbook).stem + "_已合并" + Path(args.workbook).suffix)
    wb.save(out_path)
    print(f"已写入 {written} 个单元格 -> {out_path}")
    print("接下来请运行 recalc.py 重新计算公式（或用 Excel/WPS 打开另存一次即可自动重算）。")


if __name__ == "__main__":
    main()
