#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于历史问答日志生成 Agent 学习文件。

输入:
  - logs/qa_queries.jsonl
  - logs/qa_feedback.jsonl

输出:
  - logs/agent_learning.json

用法:
  python3 train_agent_from_logs.py
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
QUERY_FILE = LOG_DIR / "qa_queries.jsonl"
FEEDBACK_FILE = LOG_DIR / "qa_feedback.jsonl"
OUT_FILE = LOG_DIR / "agent_learning.json"

STOPWORDS = {
    "什么",
    "怎么",
    "如何",
    "一个",
    "一下",
    "可以",
    "是否",
    "这个",
    "那个",
    "问题",
    "报告",
    "分析",
    "情况",
    "一下子",
    "一下吧",
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", (text or "").lower())


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _queries_for_training(items: list[dict]) -> list[dict]:
    """排除仅用于「已收到提问」的 accepted 行，避免与 completed 重复统计。"""
    return [x for x in items if x.get("phase") != "accepted"]


def _top_keywords_by_intent(query_items: list[dict], top_n: int = 20) -> dict[str, list[str]]:
    by_intent: dict[str, Counter] = defaultdict(Counter)
    for item in query_items:
        intent = (item.get("intent") or "general").strip() or "general"
        q = (item.get("question") or "").strip()
        if not q:
            continue
        for tk in _tokenize(q):
            if tk in STOPWORDS or len(tk) < 2:
                continue
            by_intent[intent][tk] += 1
    result: dict[str, list[str]] = {}
    for intent, counter in by_intent.items():
        result[intent] = [k for k, _ in counter.most_common(top_n)]
    return result


def _build_synonyms(query_items: list[dict], top_n: int = 8) -> dict[str, list[str]]:
    """
    从成功问答里统计词共现，抽取简易同义词簇。
    注意：这是启发式“检索扩展词”，不是严格语义同义词。
    """
    cooccur: dict[str, Counter] = defaultdict(Counter)
    for item in query_items:
        if item.get("empty_result"):
            continue
        q = (item.get("question") or "").strip()
        toks = [t for t in set(_tokenize(q)) if t not in STOPWORDS and len(t) >= 2]
        if len(toks) < 2:
            continue
        for a in toks:
            for b in toks:
                if a == b:
                    continue
                cooccur[a][b] += 1

    out: dict[str, list[str]] = {}
    for key, counter in cooccur.items():
        related = [w for w, c in counter.most_common(top_n) if c >= 2]
        if related:
            out[key] = related
    return out


def _intent_example_questions(query_items: list[dict], per_intent: int = 10) -> dict[str, list[str]]:
    """每个 intent 下出现次数最多的原始问句，用于线上意图对齐（token 重叠）。"""
    by_intent: dict[str, Counter] = defaultdict(Counter)
    for item in query_items:
        intent = (item.get("intent") or "general").strip() or "general"
        q = (item.get("question") or "").strip()
        if len(q) < 4:
            continue
        by_intent[intent][q] += 1
    out: dict[str, list[str]] = {}
    for intent, ctr in by_intent.items():
        out[intent] = [ques for ques, _ in ctr.most_common(per_intent)]
    return out


def _feedback_pairs(feedback_items: list[dict], top_n: int = 300) -> list[dict]:
    pairs: list[dict] = []
    for item in feedback_items:
        if item.get("is_correct") is not False:
            continue
        q = (item.get("question") or "").strip()
        expected = (item.get("expected_answer") or item.get("comment") or "").strip()
        if not q or not expected:
            continue
        pairs.append(
            {
                "question": q,
                "province": (item.get("province") or "").strip(),
                "intent": (item.get("intent") or "").strip(),
                "hint": expected[:500],
            }
        )
    return pairs[:top_n]


def main() -> None:
    query_items = _load_jsonl(QUERY_FILE)
    feedback_items = _load_jsonl(FEEDBACK_FILE)
    train_queries = _queries_for_training(query_items)

    learning = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_count": len(query_items),
        "query_count_training": len(train_queries),
        "feedback_count": len(feedback_items),
        "intent_keywords": _top_keywords_by_intent(train_queries),
        "intent_example_questions": _intent_example_questions(train_queries),
        "query_synonyms": _build_synonyms(train_queries),
        "feedback_pairs": _feedback_pairs(feedback_items),
    }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(learning, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Saved: {OUT_FILE} (lines={len(query_items)}, training_rows={len(train_queries)}, feedback={len(feedback_items)})"
    )
    if not query_items and not feedback_items:
        print("提示: logs/qa_queries.jsonl 与 logs/qa_feedback.jsonl 暂无数据；站点运行后问答会追加日志，再运行本脚本即可。")


if __name__ == "__main__":
    main()
