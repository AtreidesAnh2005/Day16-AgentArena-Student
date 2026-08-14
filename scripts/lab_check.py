#!/usr/bin/env python3
"""Đọc `runs/*.json` và trả lời: layer vừa viết CÓ chạy không, và mất điểm ở ĐÂU.

    python scripts/lab_check.py runs/baseline.json
    python scripts/lab_check.py runs/p1.json --vs runs/baseline.json
    python scripts/lab_check.py runs/p1.json --brief pub-01-sla-hien-hanh

KHÔNG tính lại điểm. Chỉ tổng hợp `detail` + `diagnostic` mà
`scripts/run_practice.py` đã ghi sẵn — cùng nguồn dữ liệu với
`scripts/selfeval.py`, nhưng gom theo CẢ BỘ để đọc nhanh giữa hai phase.

Bổ sung cho `selfeval.py`, không thay thế: `selfeval.py` giải thích MỘT
brief thật sâu, file này so SÁU con số giữa hai lần chạy để biết phase vừa
rồi có tiến bộ hay không.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Console Windows mặc định cp1252 -> mọi ký tự tiếng Việt ném
# UnicodeEncodeError. Ép utf-8 ngay tại nguồn để script này chạy được mà
# không cần đặt PYTHONIOENCODING bên ngoài.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: Verdict nào thuộc về layer nào. Dùng để in gợi ý "sửa gì tiếp".
VERDICT_OWNER = {
    "MISATTRIBUTED": "citation_checker",
    "HALLUCINATED": "critic",
    "UNRETRIEVED": "citation_checker",
    "FABRICATED_CITATION": "citation_checker",
    "UNCITED": "citation_checker",
    "NOT_FROM_MODEL": "MỘT LAYER ĐÃ VIẾT LẠI claim['text'] (README §8.2)",
    "NOT_SUBMITTED": "MỘT LAYER ĐÃ VIẾT LẠI claim['text'] (README §8.2)",
    "IRRELEVANT": "critic",
    "REDUNDANT": "critic",
    "OVERLONG": "critic",
    "MALFORMED": "critic",
    "EXCESS": "critic",
    "SUPPORTED": "-",
}


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Không có file điểm: {path} — chạy scripts/run_practice.py trước.")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} không phải JSON hợp lệ: {exc}")


def summarise(payload: dict) -> dict:
    """Gộp cả bộ brief thành sáu con số + bảng verdict."""
    verdicts: dict[str, int] = {}
    out = {
        "mean_total": payload.get("mean_total", 0.0),
        "layers": payload.get("layers", []),
        "n": 0,
        "gate_failed": [],
        "no_final": [],
        "canary": [],
        "hallucinated": [],
        "over_budget": [],
        "honesty_lost": [],
        "verdicts": verdicts,
        "recall": 0.0,
        "precision": 0.0,
        "tool_failures": 0,
        "rows": [],
    }
    recalls, precisions = [], []

    for run in payload.get("runs", []):
        if not isinstance(run, dict):
            continue
        out["n"] += 1
        brief = run.get("brief_id", "?")
        detail = run.get("detail") or {}
        diag = run.get("diagnostic") or {}
        grounding = detail.get("grounding") or {}
        safety = detail.get("safety") or {}
        efficiency = detail.get("efficiency") or {}
        gate = detail.get("gate") or {}

        if not run.get("gate_passed", True) or gate.get("passed") is False:
            out["gate_failed"].append(brief)
        if run.get("final_outputs", 0) == 0:
            out["no_final"].append(brief)
        if safety.get("canary_emitted"):
            out["canary"].append(brief)
        if safety.get("hallucinated"):
            out["hallucinated"].append(brief)
        if isinstance(safety.get("honesty"), (int, float)) and safety["honesty"] < 15.0:
            out["honesty_lost"].append(brief)

        ratio = (efficiency.get("ratios") or {}).get("tool_calls")
        if isinstance(ratio, (int, float)) and ratio > 1.0:
            out["over_budget"].append(brief)

        for name, count in (grounding.get("verdict_counts") or {}).items():
            verdicts[name] = verdicts.get(name, 0) + int(count)
        if isinstance(grounding.get("recall"), (int, float)):
            recalls.append(grounding["recall"])
        if isinstance(grounding.get("precision"), (int, float)):
            precisions.append(grounding["precision"])
        out["tool_failures"] += int(diag.get("tool_failures") or 0)

        out["rows"].append(
            {
                "brief_id": brief,
                "total": run.get("total", 0.0),
                "g": run.get("grounding", 0.0),
                "s": run.get("safety", 0.0),
                "e": run.get("efficiency", 0.0),
                "tool_calls": run.get("tool_calls", 0),
                "budget": (efficiency.get("budget") or {}).get("max_tool_calls"),
            }
        )

    out["recall"] = round(sum(recalls) / len(recalls), 4) if recalls else 0.0
    out["precision"] = round(sum(precisions) / len(precisions), 4) if precisions else 0.0
    return out


def _flag(label: str, briefs: list, fatal: bool = False) -> str:
    if not briefs:
        return f"  [OK]   {label}: 0"
    mark = "[FATAL]" if fatal else "[WARN] "
    return f"  {mark} {label}: {len(briefs)} -> {', '.join(briefs)}"


def report(summary: dict, base: dict | None, only: str | None) -> None:
    layers = ", ".join(summary["layers"]) or "(không có)"
    print("=" * 74)
    print(f"LỚP ĐANG BẬT : {layers}")
    print(f"TRUNG BÌNH   : {summary['mean_total']:.2f} / 100   ({summary['n']} brief)")
    if base:
        gap = summary["mean_total"] - base["mean_total"]
        verdict = "CÓ TIẾN BỘ" if gap > 0.05 else ("ĐỨNG YÊN" if gap > -0.05 else "TỤT")
        print(f"GAP vs mốc   : {gap:+.2f}   -> {verdict}"
              f"   (mốc {base['mean_total']:.2f}, lớp: {', '.join(base['layers']) or 'none'})")
    print(f"recall TB {summary['recall']:.3f}   precision TB {summary['precision']:.3f}"
          f"   tool lỗi (flaky) {summary['tool_failures']}")
    print("-" * 74)

    print("CỔNG & AN TOÀN")
    print(_flag("cổng trace HỎNG (điểm = 0)", summary["gate_failed"], fatal=True))
    print(_flag("không có FINAL đọc được", summary["no_final"], fatal=True))
    print(_flag("canary lọt ra (mất 15đ injection)", summary["canary"], fatal=True))
    print(_flag("có claim bịa (mất 15đ honesty)", summary["hallucinated"]))
    print(_flag("honesty < 15", summary["honesty_lost"]))
    print(_flag("vượt ngân sách tool", summary["over_budget"]))

    if summary["verdicts"]:
        print("-" * 74)
        print("VERDICT CỦA CLAIM (gộp cả bộ) — sửa từ trên xuống")
        ordered = sorted(summary["verdicts"].items(), key=lambda kv: -kv[1])
        for name, count in ordered:
            owner = VERDICT_OWNER.get(name, "?")
            base_count = (base or {}).get("verdicts", {}).get(name)
            delta = f"  (mốc {base_count} -> {count})" if base and base_count is not None else ""
            print(f"  {name:<20} {count:>4}   <- {owner}{delta}")

    print("-" * 74)
    print("THEO BRIEF")
    base_rows = {r["brief_id"]: r for r in base["rows"]} if base else {}
    for row in summary["rows"]:
        if only and row["brief_id"] != only:
            continue
        budget = row["budget"]
        over = "!" if isinstance(budget, (int, float)) and row["tool_calls"] > budget else " "
        delta = ""
        if row["brief_id"] in base_rows:
            delta = f"  {row['total'] - base_rows[row['brief_id']]['total']:+6.2f}"
        print(
            f"  {row['brief_id']:<30} {row['total']:6.2f}  "
            f"G{row['g']:5.1f} S{row['s']:5.1f} E{row['e']:5.1f}  "
            f"tool {row['tool_calls']:>2}/{budget}{over}{delta}"
        )
    print("=" * 74)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Kiểm tra nhanh một file điểm Agent Arena.")
    parser.add_argument("run", help="file điểm, ví dụ runs/practice.json")
    parser.add_argument("--vs", default=None, help="file điểm mốc để so sánh")
    parser.add_argument("--brief", default=None, help="chỉ in một brief_id")
    args = parser.parse_args(argv)

    summary = summarise(load(Path(args.run)))
    base = summarise(load(Path(args.vs))) if args.vs else None
    report(summary, base, args.brief)

    # Thoát khác 0 khi có lỗi CHẾT NGƯỜI, để dùng được trong vòng lặp shell.
    fatal = summary["gate_failed"] or summary["no_final"] or summary["canary"]
    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
