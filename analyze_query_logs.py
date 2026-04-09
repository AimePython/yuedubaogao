#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 logs/qa_queries.jsonl 生成检索优化建议。

用法:
    python3 analyze_query_logs.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "logs" / "qa_queries.jsonl"
OUT_FILE = ROOT / "logs" / "query_optimization_suggestions.json"


def load_items() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: list[dict] = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> None:
    items = [x for x in load_items() if x.get("phase") != "accepted"]
    if not items:
        print("No query logs found.")
        return

    failed = [x for x in items if x.get("empty_result")]
    failed_q = [(x.get("question") or "").strip() for x in failed if (x.get("question") or "").strip()]
    failed_counter = Counter(failed_q)

    by_intent = defaultdict(int)
    by_province = defaultdict(int)
    for x in failed:
        by_intent[x.get("intent") or "general"] += 1
        by_province[x.get("province") or "unspecified"] += 1

    result = {
        "total_queries": len(items),
        "failed_queries": len(failed),
        "top_failed_questions": [{"question": q, "count": c} for q, c in failed_counter.most_common(50)],
        "failed_by_intent": dict(sorted(by_intent.items(), key=lambda kv: kv[1], reverse=True)),
        "failed_by_province": dict(sorted(by_province.items(), key=lambda kv: kv[1], reverse=True)),
        "suggestions": [
            "优先补充 top_failed_questions 中出现频率最高的问题同义词。",
            "对 failed_by_province 靠前省份补充该省专有术语（机组、负荷、分时表述）。",
            "对 failed_by_intent 靠前意图加强规则模板与数值抽取。"
        ],
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved suggestions to: {OUT_FILE}")


if __name__ == "__main__":
    main()
