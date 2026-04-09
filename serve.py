#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地静态网站服务：托管当前目录下的 index.html、山东市场运营分析报告.html 等文件。

用法（在终端中）:
    cd "/Users/1916597037qq.com/Desktop/市场洞察网站"
    python3 serve.py

浏览器访问: http://127.0.0.1:8080/index.html
按 Ctrl+C 停止服务。
"""

from __future__ import annotations

import http.server
import json
import os
import re
import socketserver
import subprocess
import time
import threading
import urllib.request
import webbrowser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# 网站根目录 = 本脚本所在文件夹
ROOT = Path(__file__).resolve().parent
PORT = int(os.getenv("PORT", "8080"))
REPORTS_DIR = ROOT / "reports"
REPORTS_JSON_PATH = ROOT / "reports.json"
LOG_DIR = ROOT / "logs"
QUERY_LOG_PATH = LOG_DIR / "qa_queries.jsonl"
FEEDBACK_LOG_PATH = LOG_DIR / "qa_feedback.jsonl"
AGENT_LEARNING_PATH = LOG_DIR / "agent_learning.json"


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    try:
        content = dotenv_path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")

LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.openai.com/v1").rstrip("/")
# 阿里云百炼可在环境变量 DASHSCOPE_API_KEY 中配置，与 OpenAI 的 LLM_API_KEY 二选一（或同时设置时优先 LLM_API_KEY）
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip() or os.getenv("DASHSCOPE_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
# deepseek-v3.2 等：百炼兼容接口支持 enable_thinking（思考链会按输出 Token 计费，见模型文档）
LLM_ENABLE_THINKING = os.getenv("LLM_ENABLE_THINKING", "false").strip().lower() in {"1", "true", "yes", "on"}
LLM_HTTP_TIMEOUT = int(os.getenv("LLM_HTTP_TIMEOUT", "90"))
CORS_ALLOW_ORIGIN = os.getenv("CORS_ALLOW_ORIGIN", "*").strip() or "*"
ENABLE_QUERY_LOG = os.getenv("ENABLE_QUERY_LOG", "true").strip().lower() in {"1", "true", "yes", "on"}
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
SESSION_MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", "3"))
ENABLE_TOOL_AGENT = os.getenv("ENABLE_TOOL_AGENT", "true").strip().lower() in {"1", "true", "yes", "on"}
TOOL_AGENT_MAX_ROUNDS = int(os.getenv("TOOL_AGENT_MAX_ROUNDS", "5"))
ENABLE_AUTO_TRAIN = os.getenv("ENABLE_AUTO_TRAIN", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTO_TRAIN_HOUR = int(os.getenv("AUTO_TRAIN_HOUR", "2"))

# OpenAI 兼容 Function Calling：最小工具集
REPORT_AGENT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_reports",
            "description": (
                "在已上线的省级电力市场报告（HTML 解析后的文本）中检索与问题相关的原文片段。"
                "必须先调用本工具获取依据，再回答用户。province 为可选省份 slug（小写英文，如 gansu、shandong）；"
                "不传则在全国报告中检索。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索用语，尽量包含省份、月份、电价/电量/供需等关键词",
                    },
                    "province": {
                        "type": "string",
                        "description": "可选。省份目录名 slug，如 gansu、shandong、zhejiang",
                    },
                },
                "required": ["query"],
            },
        },
    }
]


def _resolve_commit() -> str:
    # Render usually provides this variable for deployed revisions.
    env_commit = os.getenv("RENDER_GIT_COMMIT", "").strip()
    if env_commit:
        return env_commit
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return commit or "unknown"
    except Exception:
        return "unknown"


APP_COMMIT = _resolve_commit()
SESSION_STORE: dict[str, list[str]] = {}
AGENT_LEARNING_CACHE: dict = {}
AGENT_LEARNING_MTIME: float = -1.0
LAST_AUTO_TRAIN_DAY: str = ""
REPORTS_MANIFEST_CACHE: dict | None = None
REPORTS_MANIFEST_MTIME: float = -1.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_query_log(item: dict) -> None:
    if not ENABLE_QUERY_LOG:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with QUERY_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError as e:
        # 日志失败不应影响主流程；打印一次便于排查「提问未落盘」
        print(f"[qa_queries] write failed: {e}", flush=True)


def _append_feedback_log(item: dict) -> None:
    if not ENABLE_QUERY_LOG:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _load_agent_learning() -> dict:
    global AGENT_LEARNING_CACHE, AGENT_LEARNING_MTIME
    if not AGENT_LEARNING_PATH.exists():
        AGENT_LEARNING_CACHE = {}
        AGENT_LEARNING_MTIME = -1.0
        return AGENT_LEARNING_CACHE
    try:
        mtime = AGENT_LEARNING_PATH.stat().st_mtime
    except OSError:
        return AGENT_LEARNING_CACHE
    if mtime == AGENT_LEARNING_MTIME and AGENT_LEARNING_CACHE:
        return AGENT_LEARNING_CACHE
    try:
        data = json.loads(AGENT_LEARNING_PATH.read_text(encoding="utf-8", errors="ignore"))
        AGENT_LEARNING_CACHE = data if isinstance(data, dict) else {}
        AGENT_LEARNING_MTIME = mtime
    except (OSError, json.JSONDecodeError):
        pass
    return AGENT_LEARNING_CACHE


def _run_training_job() -> tuple[bool, str]:
    global AGENT_LEARNING_MTIME
    try:
        proc = subprocess.run(
            ["python3", str(ROOT / "train_agent_from_logs.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as e:
        return False, f"训练执行失败: {e}"
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[-300:]
        stdout = (proc.stdout or "").strip()[-300:]
        return False, f"训练脚本失败: {stderr or stdout or 'unknown error'}"
    # 强制刷新缓存
    AGENT_LEARNING_MTIME = -1.0
    _load_agent_learning()
    return True, "ok"


def _auto_train_loop() -> None:
    """每晚固定时刻自动训练（默认 02:00）。"""
    global LAST_AUTO_TRAIN_DAY
    while True:
        try:
            now = datetime.now()
            day_key = now.strftime("%Y-%m-%d")
            if now.hour == AUTO_TRAIN_HOUR and now.minute == 0 and LAST_AUTO_TRAIN_DAY != day_key:
                ok, msg = _run_training_job()
                LAST_AUTO_TRAIN_DAY = day_key if ok else LAST_AUTO_TRAIN_DAY
                status = "OK" if ok else "FAIL"
                print(f"[auto-train] {status} day={day_key} msg={msg}")
                # 避免同一分钟重复触发
                time.sleep(65)
                continue
        except Exception as e:
            print(f"[auto-train] loop error: {e}")
        time.sleep(20)


def _read_query_logs(limit: int = 2000) -> list[dict]:
    if not QUERY_LOG_PATH.exists():
        return []
    try:
        lines = QUERY_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    items: list[dict] = []
    for line in lines[-limit:]:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def _read_feedback_logs(limit: int = 2000) -> list[dict]:
    if not FEEDBACK_LOG_PATH.exists():
        return []
    try:
        lines = FEEDBACK_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    items: list[dict] = []
    for line in lines[-limit:]:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def _build_log_stats(limit: int = 2000) -> dict:
    items = _read_query_logs(limit=limit)
    feedback_items = _read_feedback_logs(limit=limit)
    learning = _load_agent_learning()
    if not items:
        return {
            "total": 0,
            "accepted_pending": 0,
            "empty_results": 0,
            "feedback_total": len(feedback_items),
            "feedback_incorrect": sum(1 for x in feedback_items if x.get("is_correct") is False),
            "mode_distribution": {},
            "intent_distribution": {},
            "province_distribution": {},
            "top_questions": [],
            "learning_generated_at": learning.get("generated_at"),
            "learning_query_count": learning.get("query_count", 0),
            "learning_feedback_count": learning.get("feedback_count", 0),
            "learning_intent_example_buckets": len(learning.get("intent_example_questions") or {})
            if isinstance(learning.get("intent_example_questions"), dict)
            else 0,
        }
    # 统计时去掉仅「已受理」的 accepted 行，避免与 completed 重复；若全是 accepted（异常中断）则仍用原列表
    stat_items = [x for x in items if x.get("phase") != "accepted"]
    if not stat_items:
        stat_items = items
    mode_counter = Counter((x.get("mode") or "unknown") for x in stat_items)
    intent_counter = Counter((x.get("intent") or "general") for x in stat_items)
    province_counter = Counter((x.get("province") or "unspecified") for x in stat_items)
    question_counter = Counter((x.get("question") or "").strip() for x in stat_items if (x.get("question") or "").strip())
    empty_results = sum(1 for x in stat_items if x.get("empty_result"))
    top_questions = [{"question": q, "count": c} for q, c in question_counter.most_common(20)]
    return {
        "total": len(stat_items),
        "accepted_pending": sum(1 for x in items if x.get("phase") == "accepted"),
        "empty_results": empty_results,
        "feedback_total": len(feedback_items),
        "feedback_incorrect": sum(1 for x in feedback_items if x.get("is_correct") is False),
        "mode_distribution": dict(mode_counter),
        "intent_distribution": dict(intent_counter),
        "province_distribution": dict(province_counter),
        "top_questions": top_questions,
        "learning_generated_at": learning.get("generated_at"),
        "learning_query_count": learning.get("query_count", 0),
        "learning_feedback_count": learning.get("feedback_count", 0),
        "learning_intent_example_buckets": len(learning.get("intent_example_questions") or {})
        if isinstance(learning.get("intent_example_questions"), dict)
        else 0,
    }


def _normalize_session_id(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    # 限制长度，避免异常输入占用内存
    return s[:64]


def _build_question_with_memory(question: str, session_id: str) -> str:
    if not session_id:
        return question
    history = SESSION_STORE.get(session_id, [])
    if not history:
        return question
    return " ".join(history[-SESSION_MAX_TURNS:] + [question]).strip()


def _update_session_memory(session_id: str, question: str) -> None:
    if not session_id:
        return
    history = SESSION_STORE.get(session_id, [])
    history.append(question.strip())
    SESSION_STORE[session_id] = history[-SESSION_MAX_TURNS:]


def _find_feedback_hint(question: str, province: str, intent: str) -> str:
    learning = _load_agent_learning()
    learned_pairs = learning.get("feedback_pairs") if isinstance(learning, dict) else []
    if isinstance(learned_pairs, list):
        q_tokens = set(_tokenize(question))
        best_score = 0
        best_hint = ""
        for item in learned_pairs:
            if not isinstance(item, dict):
                continue
            if province and item.get("province") and item.get("province") != province:
                continue
            if intent and item.get("intent") and item.get("intent") != intent:
                continue
            old_q = (item.get("question") or "").strip()
            hint = (item.get("hint") or "").strip()
            if not old_q or not hint:
                continue
            overlap = len(q_tokens & set(_tokenize(old_q)))
            if overlap > best_score:
                best_score = overlap
                best_hint = hint
        if best_score >= 2 and best_hint:
            return best_hint[:300]

    items = _read_feedback_logs(limit=300)
    if not items:
        return ""
    q_tokens = set(_tokenize(question))
    best_score = 0
    best_hint = ""
    for item in items:
        if item.get("is_correct") is not False:
            continue
        if province and item.get("province") and item.get("province") != province:
            continue
        if intent and item.get("intent") and item.get("intent") != intent:
            continue
        old_q = (item.get("question") or "").strip()
        if not old_q:
            continue
        overlap = len(q_tokens & set(_tokenize(old_q)))
        if overlap <= best_score:
            continue
        expected = (item.get("expected_answer") or item.get("comment") or "").strip()
        if not expected:
            continue
        best_score = overlap
        best_hint = expected
    if best_score >= 2:
        return best_hint[:300]
    return ""

PROVINCE_ALIASES: dict[str, str] = {
    "北京市": "beijing",
    "北京": "beijing",
    "天津市": "tianjin",
    "天津": "tianjin",
    "河北省": "hebei",
    "河北": "hebei",
    "山西省": "shanxi",
    "山西": "shanxi",
    "内蒙古自治区": "neimenggu",
    "内蒙古": "neimenggu",
    "辽宁省": "liaoning",
    "辽宁": "liaoning",
    "吉林省": "jilin",
    "吉林": "jilin",
    "黑龙江省": "heilongjiang",
    "黑龙江": "heilongjiang",
    "上海市": "shanghai",
    "上海": "shanghai",
    "江苏省": "jiangsu",
    "江苏": "jiangsu",
    "浙江省": "zhejiang",
    "浙江": "zhejiang",
    "安徽省": "anhui",
    "安徽": "anhui",
    "福建省": "fujian",
    "福建": "fujian",
    "江西省": "jiangxi",
    "江西": "jiangxi",
    "山东省": "shandong",
    "山东": "shandong",
    "河南省": "henan",
    "河南": "henan",
    "湖北省": "hubei",
    "湖北": "hubei",
    "湖南省": "hunan",
    "湖南": "hunan",
    "广东省": "guangdong",
    "广东": "guangdong",
    "广西壮族自治区": "guangxi",
    "广西": "guangxi",
    "海南省": "hainan",
    "海南": "hainan",
    "重庆市": "chongqing",
    "重庆": "chongqing",
    "四川省": "sichuan",
    "四川": "sichuan",
    "贵州省": "guizhou",
    "贵州": "guizhou",
    "云南省": "yunnan",
    "云南": "yunnan",
    "西藏自治区": "xizang",
    "西藏": "xizang",
    "陕西省": "shanxi1",
    "陕西": "shanxi1",
    "甘肃省": "gansu",
    "甘肃": "gansu",
    "青海省": "qinghai",
    "青海": "qinghai",
    "宁夏回族自治区": "ningxia",
    "宁夏": "ningxia",
    "新疆维吾尔自治区": "xinjiang",
    "新疆": "xinjiang",
}

QUERY_SYNONYMS: dict[str, list[str]] = {
    "现货价差": ["价差", "峰谷", "峰谷价差", "分时价差", "现货"],
    "最低价格": ["最低", "低谷", "低价", "最低价", "最低时段"],
    "倒挂": ["倒挂", "高于", "低于", "中长期", "现货"],
    "供需关系": ["供需", "平衡", "偏紧", "偏松", "外送", "负荷"],
}


def _strip_html(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", text.lower())


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r"[。！？；\n]+", text)
    out: list[str] = []
    for raw in sentences:
        s = raw.strip()
        if not s:
            continue
        if len(s) < 8 or len(s) > 180:
            continue
        zh_chars = len(re.findall(r"[\u4e00-\u9fff]", s))
        if zh_chars / max(len(s), 1) < 0.2:
            continue
        # 过滤明显表头/图例拼接噪声
        if re.search(r"(月份\s+类型\s+发电量|24小时|条形图|展示所选日期|注：)", s):
            continue
        out.append(s)
    return out


def _detect_province_from_question(question: str) -> str:
    q = question.strip()
    for name, slug in PROVINCE_ALIASES.items():
        if name in q:
            return slug
    return ""


def _detect_intent(question: str) -> str:
    q = question
    if "价差" in q:
        return "spot_spread"
    if "最低" in q or "比较低" in q or "低谷" in q:
        return "spot_low_time"
    if "倒挂" in q or ("现货" in q and "中长期" in q and ("高于" in q or "低于" in q or "关系" in q)):
        return "price_inversion"
    if "供需" in q or "供需关系" in q:
        return "supply_demand"
    learning = _load_agent_learning()
    if isinstance(learning, dict):
        examples = learning.get("intent_example_questions")
        if isinstance(examples, dict):
            q_tokens = set(_tokenize(q))
            best_intent = ""
            best_score = 0
            for intent, phrases in examples.items():
                if not isinstance(phrases, list):
                    continue
                for phrase in phrases:
                    ph = str(phrase).strip()
                    if len(ph) < 4:
                        continue
                    sc = len(q_tokens & set(_tokenize(ph)))
                    if sc > best_score:
                        best_score = sc
                        best_intent = str(intent)
            if best_intent and best_score >= 2:
                return best_intent
    intent_keywords = learning.get("intent_keywords") if isinstance(learning, dict) else {}
    if isinstance(intent_keywords, dict):
        q_tokens = set(_tokenize(q))
        best_intent = ""
        best_score = 0
        for intent, words in intent_keywords.items():
            if not isinstance(words, list):
                continue
            overlap = len(q_tokens & set(str(w) for w in words))
            if overlap > best_score:
                best_score = overlap
                best_intent = str(intent)
        if best_intent and best_score >= 2:
            return best_intent
    return "general"


def _expand_query_tokens(question: str) -> set[str]:
    tokens = set(_tokenize(question))
    for key, words in QUERY_SYNONYMS.items():
        if key in question or any(w in question for w in words):
            tokens.update(words)
    learning = _load_agent_learning()
    learned_synonyms = learning.get("query_synonyms") if isinstance(learning, dict) else {}
    if isinstance(learned_synonyms, dict):
        for tk in list(tokens):
            related = learned_synonyms.get(tk)
            if isinstance(related, list):
                tokens.update(str(x) for x in related[:12])
    return {t.lower() for t in tokens}


def _load_reports_manifest() -> dict:
    """已发布报告注册表（与首页 province 卡片一致）。"""
    global REPORTS_MANIFEST_CACHE, REPORTS_MANIFEST_MTIME
    if not REPORTS_JSON_PATH.exists():
        return {}
    try:
        mtime = REPORTS_JSON_PATH.stat().st_mtime
    except OSError:
        return {}
    if REPORTS_MANIFEST_CACHE is not None and mtime == REPORTS_MANIFEST_MTIME:
        return REPORTS_MANIFEST_CACHE
    try:
        raw = json.loads(REPORTS_JSON_PATH.read_text(encoding="utf-8", errors="ignore"))
        REPORTS_MANIFEST_CACHE = raw if isinstance(raw, dict) else {}
        REPORTS_MANIFEST_MTIME = mtime
    except (OSError, json.JSONDecodeError):
        REPORTS_MANIFEST_CACHE = {}
        REPORTS_MANIFEST_MTIME = mtime
    return REPORTS_MANIFEST_CACHE


def _slug_to_label(slug: str) -> str:
    names = [n for n, s in PROVINCE_ALIASES.items() if s == slug]
    if not names:
        return slug
    return min(names, key=len)


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "两": 2}


def _chinese_month_to_int(s: str) -> int | None:
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        m = int(s)
        return m if 1 <= m <= 12 else None
    if s in ("十", "十一", "十二"):
        return {"十": 10, "十一": 11, "十二": 12}[s]
    if s.startswith("十") and len(s) == 2:
        u = s[1]
        if u in _CN_NUM:
            return 10 + _CN_NUM[u]
    if s.endswith("月"):
        s = s[:-1]
    if len(s) == 1 and s in _CN_NUM:
        v = _CN_NUM[s]
        return v if 1 <= v <= 12 else None
    if s == "十":
        return 10
    return None


def _parse_year_month_for_inventory(q: str) -> tuple[int, int] | None:
    """从问句解析 (年, 月)；缺省年份用环境变量或当前年。"""
    default_year = int(os.getenv("REPORT_INVENTORY_DEFAULT_YEAR", str(datetime.now().year)))
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", q)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return y, mo
    m = re.search(r"(20\d{2})\s*年\s*([一二三四五六七八九十两]+)\s*月", q)
    if m:
        y = int(m.group(1))
        mo = _chinese_month_to_int(m.group(2))
        if mo:
            return y, mo
    m = re.search(r"(?<![\d/])(\d{1,2})\s*月", q)
    if m:
        mo = int(m.group(1))
        if 1 <= mo <= 12:
            return default_year, mo
    m = re.search(r"([一二三四五六七八九十两]+)\s*月", q)
    if m:
        mo = _chinese_month_to_int(m.group(1))
        if mo:
            return default_year, mo
    m = re.search(r"(20\d{2})-(\d{2})\b", q)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return y, mo
    return None


def _is_report_inventory_question(q: str) -> bool:
    """是否在问「哪些省份已上线某月报告」类清单（非单省行情）。"""
    qn = re.sub(r"\s+", "", q)
    if len(qn) < 6:
        return False
    if not (
        re.search(r"\d{1,2}\s*月", q)
        or re.search(r"[一二三四五六七八九十两]+\s*月", q)
        or re.search(r"20\d{2}-\d{2}", q)
        or re.search(r"20\d{2}\s*年", q)
    ):
        return False
    scope = any(
        x in qn
        for x in (
            "哪些",
            "哪几个",
            "有哪些",
            "都有谁",
            "所有省",
            "全部省",
            "各省",
            "每个省",
            "省份",
            "个省",
            "列出",
            "查找",
            "检索",
            "统计",
            "汇总",
        )
    )
    meta = any(x in qn for x in ("报告", "披露", "上线", "上传", "发布", "html", "月报"))
    if not scope:
        return False
    if "省份" in qn or "个省" in qn:
        return meta or "月" in qn
    return meta


def _try_report_month_inventory_answer(question: str) -> tuple[str, list[dict], dict] | None:
    """
    若问句为「已发布某月报告的省份列表」，直接读 reports.json 回答（不经片段检索）。
    返回 (answer, sources, trust_meta) 或 None。
    """
    if not _is_report_inventory_question(question):
        return None
    ym = _parse_year_month_for_inventory(question)
    if not ym:
        return None
    year, month = ym
    key = f"{year}-{month:02d}"
    manifest = _load_reports_manifest()
    if not manifest:
        return None
    rows: list[tuple[str, str, str, str]] = []
    for slug in sorted(manifest.keys()):
        prov_data = manifest.get(slug)
        if not isinstance(prov_data, dict):
            continue
        entry = prov_data.get(key)
        if not isinstance(entry, dict):
            continue
        path = (entry.get("file") or "").strip().replace("\\", "/")
        label = (entry.get("label") or "").strip()
        if not path:
            continue
        name = _slug_to_label(slug)
        rows.append((name, slug, path, label))

    if not rows:
        note = (
            f"本站 reports.json 中尚未注册 **{year}年{month}月**（键 {key}）的省级报告。"
            "若刚上传 HTML，请同步更新 reports.json 后重试。"
        )
        trust = {
            "evidence_strength": "high",
            "numeric_grounding": "ok",
            "notes": ["依据为项目根目录 reports.json，非模型推测。"],
        }
        return note, [], trust

    lines = [
        f"根据本站 **reports.json** 注册表（与首页已上线省份一致），**{year}年{month}月** 已配置报告的省级行政区共 **{len(rows)}** 个："
    ]
    sources: list[dict] = []
    for i, (name, slug, path, label) in enumerate(rows, start=1):
        lab = f"（{label}）" if label else ""
        lines.append(f"{i}. **{name}**（slug: `{slug}`）{lab} → `{path}`")
        sources.append({"province": slug, "file": path})
    lines.append(
        "\n说明：以上为站点发布目录，不是全文检索结果；若需某省行情细节，请点名省份后再问。"
    )
    trust = {
        "evidence_strength": "high",
        "numeric_grounding": "ok",
        "notes": ["清单完全来自 reports.json，可按路径打开 HTML 核对。"],
    }
    return "\n".join(lines), sources, trust


def _build_corpus() -> list[dict]:
    docs: list[dict] = []
    if not REPORTS_DIR.exists():
        return docs
    for html_path in sorted(REPORTS_DIR.rglob("*.html")):
        try:
            raw = html_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        text = _strip_html(raw)
        if not text:
            continue
        docs.append(
            {
                "path": str(html_path.relative_to(ROOT)).replace("\\", "/"),
                "province": html_path.parent.name,
                "text": text,
                "tokens": set(_tokenize(text)),
                "sentences": _split_sentences(text),
            }
        )
    return docs


def _extract_snippet(text: str, question: str, max_len: int = 220) -> str:
    q_tokens = _tokenize(question)
    pos = -1
    for tk in q_tokens:
        pos = text.lower().find(tk)
        if pos >= 0:
            break
    if pos < 0:
        return text[:max_len] + ("..." if len(text) > max_len else "")
    start = max(0, pos - max_len // 3)
    end = min(len(text), start + max_len)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet += "..."
    return snippet


def _search_relevant_docs(docs: list[dict], question: str, province: str, top_k: int = 4) -> list[tuple[int, dict]]:
    q_tokens = _expand_query_tokens(question)
    scoped_docs = docs
    if province:
        scoped_docs = [d for d in docs if d["province"].lower() == province]
    if not scoped_docs:
        return []
    if not q_tokens:
        # 已指定省份但问题过短时，仍返回该省报告供后续兜底回答
        return [(0, d) for d in scoped_docs[:top_k]]
    scored: list[tuple[int, dict]] = []
    for d in scoped_docs:
        overlap = len(q_tokens & d["tokens"])
        if overlap > 0:
            scored.append((overlap, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        return scored[:top_k]
    if province:
        # 指定省份但未命中关键词时，退化到“按省份直取”避免空答案
        return [(0, d) for d in scoped_docs[:top_k]]
    return []


def _fallback_answer(question: str, top_docs: list[tuple[int, dict]]) -> str:
    if not top_docs:
        return "未在已收录的省级报告中检索到直接相关表述，可尝试换一种问法或指定省份后再问。"
    lines = ["根据当前检索，与问题相关的报告片段如下（建议点开来源全文核对）："]
    for score, doc in top_docs:
        lines.append(f"- {doc['province']}（相关度 {score}）：{_extract_snippet(doc['text'], question)}")
    return "\n".join(lines)


def _extract_metric_sentences(sentences: list[str], intent: str) -> list[str]:
    if intent == "spot_spread":
        pats = [r"价差", r"峰谷", r"现货", r"分时", r"峰时", r"谷时"]
    elif intent == "spot_low_time":
        pats = [r"最低", r"低谷", r"低价", r"谷段", r"时段", r"时"]
    elif intent == "price_inversion":
        pats = [r"中长期", r"现货", r"倒挂", r"高于", r"低于", r"均价"]
    elif intent == "supply_demand":
        pats = [r"供需", r"平衡", r"偏紧", r"偏松", r"外送", r"负荷", r"备用"]
    else:
        pats = [r"现货", r"中长期", r"供需", r"价格"]
    reg = re.compile("|".join(pats))
    ranked = [s for s in sentences if reg.search(s) and len(s) >= 8]
    return ranked[:6]


def _build_structured_answer(question: str, top_docs: list[tuple[int, dict]], intent: str) -> str:
    if not top_docs:
        return _fallback_answer(question, top_docs)
    doc = top_docs[0][1]
    sentences = doc.get("sentences", [])
    key_sents = _extract_metric_sentences(sentences, intent)
    if not key_sents:
        return _fallback_answer(question, top_docs)

    text = doc.get("text", "")
    lines: list[str] = []

    if intent == "spot_spread":
        spread_sents = [s for s in key_sents if ("价差" in s or "峰谷" in s)]
        lines.append("简要结论：现货价差（以下句子摘自报告原文）")
        if spread_sents:
            lines.append(f"- {spread_sents[0]}")
        else:
            lines.append("- 报告未直接给出“现货价差”统一口径，以下提供可反映价差特征的原文依据。")
            for s in key_sents[:2]:
                lines.append(f"- {s}")
        return "\n".join(lines)

    if intent == "spot_low_time":
        low_time_sents = [s for s in sentences if re.search(r"(最低|低谷|谷段|时段|点|小时)", s)]
        lines.append("简要结论：现货低价时段（以下句子摘自报告原文）")
        if low_time_sents:
            lines.append(f"- {low_time_sents[0]}")
        else:
            lines.append("- 报告中未明确写出最低价对应具体时段，建议结合分时曲线进一步确认。")
            for s in key_sents[:2]:
                lines.append(f"- {s}")
        return "\n".join(lines)

    if intent == "price_inversion":
        spot_vals = re.findall(r"(?:现货|实时|日前)[^。；]{0,20}(?:均价|价格)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)", text)
        mid_vals = re.findall(r"(?:中长期)[^。；]{0,20}(?:均价|价格)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)", text)
        lines.append("简要结论：现货与中长期价格关系（以下摘自报告原文）")
        if spot_vals and mid_vals:
            try:
                spot = float(spot_vals[0])
                mid = float(mid_vals[0])
                judge = "存在倒挂（现货高于中长期）" if spot > mid else "未出现倒挂（现货不高于中长期）"
                lines.append(f"- 判断：{judge}。现货约 {spot:.2f} 元/MWh，中长期约 {mid:.2f} 元/MWh。")
            except ValueError:
                pass
        for s in key_sents[:2]:
            lines.append(f"- {s}")
        return "\n".join(lines)

    if intent == "supply_demand":
        sd_sents = [s for s in sentences if re.search(r"(供需|平衡|偏紧|偏松|外送|负荷|备用)", s)]
        lines.append("简要结论：供需关系（以下句子摘自报告原文）")
        if sd_sents:
            lines.append(f"- {sd_sents[0]}")
            for s in sd_sents[1:3]:
                lines.append(f"- {s}")
        else:
            for s in key_sents[:3]:
                lines.append(f"- {s}")
        return "\n".join(lines)

    lines.append("简要结论（以下句子摘自报告原文）")
    for s in key_sents[:3]:
        lines.append(f"- {s}")
    return "\n".join(lines)


def _build_agent_context(question: str, top_docs: list[tuple[int, dict]]) -> str:
    chunks: list[str] = []
    for idx, (_, doc) in enumerate(top_docs, start=1):
        chunks.append(
            f"[文档{idx}] 省份: {doc['province']}\n"
            f"路径: {doc['path']}\n"
            f"片段: {_extract_snippet(doc['text'], question, max_len=420)}"
        )
    return "\n\n".join(chunks)


# 表达气质参考 DeepSeek 类对话：先结论、再分点、纯文本、少套话
LLM_PERSONA_STYLE = (
    "表达风格：语气理性、简洁，像 DeepSeek 常见回答那样先给出 1～2 句核心结论，再用「1.」「2.」分点展开依据与数据；避免套话、堆砌感叹词和表情符号。"
    "段落之间可空一行，便于扫读；仅用纯文本与中文标点，不要使用 Markdown 标题/代码块或 LaTeX。"
    "可用「根据检索到的报告片段」「综合来看」等自然衔接；除非确实无资料可答，否则不要输出「作为人工智能」类免责声明。"
)

# 更准、更敢用：与模型约束、数值对齐、证据强度
LLM_SYSTEM_TRUST_RULES = (
    "严格规则："
    "1) 所有具体数字、日期、电价/电量/装机等量化表述必须能在「可用资料」或工具 hits 的 snippet 中找到依据；找不到就写「资料片段中未出现该数值，需查看完整报告」。"
    "2) 禁止推测、禁止用常识补全报告中没有的内容。"
    "3) 每条结论尽量标注依据来自哪条 path（报告文件路径）。"
    "4) 若资料不足以回答问题，直接说明不足，不要编造。"
)

AGENT_TEMPERATURE = float(os.getenv("AGENT_TEMPERATURE", "0.15"))


def _llm_optional_compat_fields() -> dict:
    """阿里云百炼 OpenAI 兼容模式下的非标准字段（如 DeepSeek 思考模式）。"""
    if not LLM_ENABLE_THINKING:
        return {}
    m = (LLM_MODEL or "").lower()
    if "deepseek" not in m:
        return {}
    return {"enable_thinking": True}


def _grounding_corpus_from_docs(top_docs: list[tuple[int, dict]], max_chars: int = 14000) -> str:
    """拼接用于数值校验的原文池（截取控制长度）。"""
    parts: list[str] = []
    n = 0
    for _, doc in top_docs:
        t = doc.get("text") or ""
        chunk = t[:4500]
        parts.append(chunk)
        n += len(chunk)
        if n >= max_chars:
            break
    return "\n".join(parts)


def _find_ungrounded_numbers(answer: str, corpus: str) -> list[str]:
    """找出回答中出现、但在原文池中未逐字出现的数字串（启发式，减少幻觉）。"""
    if not answer or not corpus:
        return []
    clean = answer.split("【可信度说明】")[0].split("【说明】")[0]
    corpus_compact = re.sub(r"\s+", "", corpus)
    # 匹配小数与整数（至少两位数字，避免误伤「3条」等）
    pattern = re.compile(r"\d+(?:\.\d+)?")
    bad: list[str] = []
    seen: set[str] = set()
    for m in pattern.finditer(clean):
        s = m.group()
        if len(re.sub(r"\D", "", s)) < 2:
            continue
        if s in seen:
            continue
        seen.add(s)
        if s in corpus or s in corpus_compact:
            continue
        bad.append(s)
        if len(bad) >= 12:
            break
    return bad


def _evidence_strength(top_docs: list[tuple[int, dict]]) -> str:
    if not top_docs:
        return "none"
    scores = [s for s, _ in top_docs]
    mx = max(scores)
    if mx == 0:
        return "low"
    if mx >= 3:
        return "high"
    return "medium"


def _augment_answer_for_trust(answer: str, top_docs: list[tuple[int, dict]]) -> tuple[str, dict]:
    """
    在回答后附加可信度说明，并返回 trust 元数据供前端展示。
    """
    corpus = _grounding_corpus_from_docs(top_docs)
    evidence = _evidence_strength(top_docs)
    ungrounded = _find_ungrounded_numbers(answer, corpus)
    numeric = "ok" if not ungrounded else "check_needed"
    trust: dict = {
        "evidence_strength": evidence,
        "numeric_grounding": numeric,
    }
    notes: list[str] = []
    if evidence == "low":
        notes.append("当前检索与问题关键词匹配偏弱，结论仅作导读，请务必对照下方「参考来源」打开原文核对。")
    if ungrounded:
        preview = "、".join(ungrounded[:5])
        if len(ungrounded) > 5:
            preview += " 等"
        notes.append(
            f"模型回答中的部分数值（{preview}）未在给定原文摘录中逐字命中，可能存在转述或幻觉，请以报告原文为准。"
        )
    if notes:
        trust["notes"] = notes
        answer = answer.rstrip() + "\n\n【可信度说明】" + " ".join(notes)
    return answer, trust


def _post_chat_completions(body: dict) -> dict | None:
    """POST /chat/completions，返回完整 JSON；失败返回 None。"""
    req = urllib.request.Request(
        url=f"{LLM_API_BASE}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _tool_search_reports_impl(
    docs: list[dict], query: str, province: str, top_k: int = 4
) -> tuple[str, list[tuple[int, dict]]]:
    top_k = max(1, min(top_k, 6))
    top = _search_relevant_docs(docs, query, province, top_k=top_k)
    hits: list[dict] = []
    for score, doc in top:
        hits.append(
            {
                "province": doc["province"],
                "path": doc["path"],
                "relevance": score,
                "snippet": _extract_snippet(doc["text"], query, max_len=520),
            }
        )
    return json.dumps({"hits": hits}, ensure_ascii=False), top


def _run_tool_agent(
    question: str,
    feedback_hint: str,
    docs: list[dict],
    default_province: str,
) -> tuple[str | None, str, list[tuple[int, dict]]]:
    """
    最小 Tool Agent：多轮调用 search_reports，再输出最终回答。
    返回 (answer, mode, top_docs_for_sources)；失败时 answer 为 None。
    """
    if not LLM_API_KEY:
        return None, "", []

    system = (
        "你是专注中国电力市场「省级分析报告」的解读助手，面向从业者用中文答疑。"
        "工作方式：必须先调用工具 search_reports 拉取报告原文片段，最终回答仅允许基于工具返回的 hits 里 snippet 中的内容；hits 为空时坦诚说明未命中、勿编造数字。"
        "最终成文：段首给简短结论，再分点列依据（每条注明 path），所引数字须与 snippet 可核对。"
        + LLM_PERSONA_STYLE
        + LLM_SYSTEM_TRUST_RULES
    )
    user_content = f"用户问题：{question}\n"
    if feedback_hint:
        user_content += f"历史纠错提示：{feedback_hint}\n"

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    last_top_docs: list[tuple[int, dict]] = []
    rounds = 0

    while rounds < TOOL_AGENT_MAX_ROUNDS:
        rounds += 1
        body = {
            "model": LLM_MODEL,
            "messages": messages,
            "tools": REPORT_AGENT_TOOLS,
            "tool_choice": "auto",
            "temperature": AGENT_TEMPERATURE,
            **_llm_optional_compat_fields(),
        }
        data = _post_chat_completions(body)
        if not data:
            return None, "", last_top_docs
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return None, "", last_top_docs

        tool_calls = msg.get("tool_calls")
        content = (msg.get("content") or "").strip()

        if tool_calls:
            assistant_msg: dict = {"role": "assistant", "content": msg.get("content")}
            assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name", "")
                args_raw = fn.get("arguments") or "{}"
                tc_id = tc.get("id") or ""
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                except json.JSONDecodeError:
                    args = {}
                if name == "search_reports":
                    q = (args.get("query") or question).strip()
                    prov = (args.get("province") or default_province or "").strip().lower()
                    payload_json, top = _tool_search_reports_impl(docs, q, prov, top_k=4)
                    last_top_docs = top
                else:
                    payload_json = json.dumps({"error": "unknown_tool", "name": name}, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": payload_json})
            continue

        if content:
            return content, "tool-agent", last_top_docs if last_top_docs else []

    # 轮次用尽：用最后一次检索结果做单次补答
    if last_top_docs:
        ctx = _build_agent_context(question, last_top_docs)
        ans = _call_llm_answer(question, ctx, feedback_hint=feedback_hint)
        if ans:
            return ans, "agent", last_top_docs
    return None, "", last_top_docs


def _call_llm_answer(question: str, context: str, feedback_hint: str = "") -> str | None:
    if not LLM_API_KEY:
        return None
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专注中国电力市场省级报告解读的助手，仅用中文作答。"
                    "只能依据下方「可用资料」回答；证据不足时直接说明缺口，勿臆测或外推。"
                    "成文顺序：先 1～2 句简要结论，再分点列出 2～4 条关键依据（每条注明 path）；若问题涉及最低电价时段、现货与中长期倒挂或供需松紧，结论段须点明判断。"
                    + LLM_PERSONA_STYLE
                    + LLM_SYSTEM_TRUST_RULES
                ),
            },
            {
                "role": "user",
                "content": (
                    f"问题：{question}\n\n"
                    + (f"历史纠错提示：{feedback_hint}\n\n" if feedback_hint else "")
                    + f"可用资料：\n{context}"
                ),
            },
        ],
        "temperature": AGENT_TEMPERATURE,
        **_llm_optional_compat_fields(),
    }
    req = urllib.request.Request(
        url=f"{LLM_API_BASE}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw)
    except Exception:
        return None
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


class SiteHandler(http.server.SimpleHTTPRequestHandler):
    """固定网站根目录为脚本所在文件夹，并为文本类资源标注 UTF-8。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
    }

    _corpus_cache: list[dict] | None = None

    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", CORS_ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_admin_allowed(self, parsed) -> bool:
        if not ADMIN_TOKEN:
            return True
        params = {}
        try:
            # keep dependency-light parsing
            query = parsed.query or ""
            for kv in query.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    params[k] = v
        except Exception:
            params = {}
        token_from_query = params.get("token", "")
        token_from_header = self.headers.get("X-Admin-Token", "")
        return token_from_query == ADMIN_TOKEN or token_from_header == ADMIN_TOKEN

    def _ensure_corpus(self) -> list[dict]:
        if self.__class__._corpus_cache is None:
            self.__class__._corpus_cache = _build_corpus()
        return self.__class__._corpus_cache

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(
                {
                    "ok": True,
                    "reports": len(self._ensure_corpus()),
                    "agent_enabled": bool(LLM_API_KEY),
                    "tool_agent_enabled": bool(LLM_API_KEY and ENABLE_TOOL_AGENT),
                    "llm_model": LLM_MODEL if LLM_API_KEY else None,
                }
            )
            return
        if parsed.path == "/api/version":
            self._send_json({"commit": APP_COMMIT})
            return
        if parsed.path == "/api/admin/stats":
            if not self._is_admin_allowed(parsed):
                self._send_json({"error": "unauthorized"}, status=401)
                return
            self._send_json(_build_log_stats())
            return
        super().do_GET()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/ask", "/api/feedback", "/api/admin/train", "/api/log-query"}:
            self.send_error(404, "Not Found")
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length).decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json({"error": "请求体必须是 JSON"}, status=400)
            return

        if parsed.path == "/api/log-query":
            # 前端走本地兜底或未连上 /api/ask 时仍记录提问，便于分析与训练
            question = (payload.get("question") or "").strip()
            if not question:
                self._send_json({"error": "question 不能为空"}, status=400)
                return
            session_id = _normalize_session_id(payload.get("session_id") or "")
            province = (payload.get("province") or "").strip().lower()
            if not province:
                province = _detect_province_from_question(question)
            reason = (payload.get("reason") or "client").strip()[:120]
            detail = (payload.get("detail") or "").strip()[:500]
            intent = _detect_intent(question)
            _append_query_log(
                {
                    "ts": _utc_now_iso(),
                    "question": question,
                    "session_id": session_id,
                    "province": province,
                    "intent": intent,
                    "mode": "client_fallback",
                    "empty_result": True,
                    "sources_count": 0,
                    "latency_ms": 0,
                    "phase": "completed",
                    "client_fallback_reason": reason,
                    "client_fallback_detail": detail,
                }
            )
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/admin/train":
            if not self._is_admin_allowed(parsed):
                self._send_json({"error": "unauthorized"}, status=401)
                return
            ok, msg = _run_training_job()
            if not ok:
                self._send_json({"error": msg}, status=500)
                return
            learning = _load_agent_learning()
            ex = learning.get("intent_example_questions") if isinstance(learning, dict) else {}
            ex_n = len(ex) if isinstance(ex, dict) else 0
            self._send_json(
                {
                    "ok": True,
                    "message": "训练完成",
                    "learning_file": str(AGENT_LEARNING_PATH.relative_to(ROOT)).replace("\\", "/"),
                    "query_count": learning.get("query_count", 0),
                    "feedback_count": learning.get("feedback_count", 0),
                    "intent_buckets_with_examples": ex_n,
                    "generated_at": learning.get("generated_at"),
                }
            )
            return

        if parsed.path == "/api/feedback":
            question = (payload.get("question") or "").strip()
            province = (payload.get("province") or "").strip().lower()
            intent = (payload.get("intent") or "").strip() or _detect_intent(question)
            is_correct = payload.get("is_correct")
            comment = (payload.get("comment") or "").strip()
            expected_answer = (payload.get("expected_answer") or "").strip()
            if not question:
                self._send_json({"error": "question 不能为空"}, status=400)
                return
            if is_correct not in {True, False}:
                self._send_json({"error": "is_correct 必须是 true/false"}, status=400)
                return
            _append_feedback_log(
                {
                    "ts": _utc_now_iso(),
                    "question": question,
                    "province": province,
                    "intent": intent,
                    "is_correct": is_correct,
                    "comment": comment,
                    "expected_answer": expected_answer,
                }
            )
            self._send_json({"ok": True})
            return

        question = (payload.get("question") or "").strip()
        session_id = _normalize_session_id(payload.get("session_id") or "")
        province = (payload.get("province") or "").strip().lower()
        question_for_retrieval = _build_question_with_memory(question, session_id)
        if not province:
            province = _detect_province_from_question(question_for_retrieval)
        intent = _detect_intent(question_for_retrieval)
        feedback_hint = _find_feedback_hint(question_for_retrieval, province, intent)
        started = time.time()

        if not question:
            self._send_json({"error": "question 不能为空"}, status=400)
            return

        if not _tokenize(question_for_retrieval):
            self._send_json(
                {
                    "answer": "问题过短，请补充关键词后重试。",
                    "sources": [],
                    "mode": "validation",
                    "trust": {
                        "evidence_strength": "none",
                        "numeric_grounding": "n/a",
                        "notes": ["未执行检索与数值校验。"],
                    },
                }
            )
            _append_query_log(
                {
                    "ts": _utc_now_iso(),
                    "question": question,
                    "session_id": session_id,
                    "province": province,
                    "intent": intent,
                    "mode": "validation",
                    "empty_result": False,
                    "sources_count": 0,
                    "latency_ms": int((time.time() - started) * 1000),
                    "phase": "completed",
                }
            )
            return

        inv = _try_report_month_inventory_answer(question_for_retrieval)
        if inv is not None:
            inv_answer, inv_sources, inv_trust = inv
            self._send_json(
                {
                    "answer": inv_answer,
                    "sources": inv_sources,
                    "mode": "report-inventory",
                    "trust": inv_trust,
                }
            )
            _update_session_memory(session_id, question)
            _append_query_log(
                {
                    "ts": _utc_now_iso(),
                    "question": question,
                    "session_id": session_id,
                    "province": province,
                    "intent": intent,
                    "mode": "report-inventory",
                    "empty_result": len(inv_sources) == 0,
                    "sources_count": len(inv_sources),
                    "latency_ms": int((time.time() - started) * 1000),
                    "phase": "completed",
                }
            )
            return

        # 已进入检索/模型流程：先落一条，避免 LLM 超时或异常导致「提问完全无记录」
        _append_query_log(
            {
                "ts": _utc_now_iso(),
                "question": question,
                "session_id": session_id,
                "province": province,
                "intent": intent,
                "phase": "accepted",
            }
        )

        docs = self._ensure_corpus()
        top_docs = _search_relevant_docs(docs, question_for_retrieval, province, top_k=4)
        if not top_docs:
            answer = _fallback_answer(question, top_docs)
            self._send_json(
                {
                    "answer": answer,
                    "sources": [],
                    "mode": "retrieval",
                    "trust": {
                        "evidence_strength": "none",
                        "numeric_grounding": "n/a",
                        "notes": ["未在已索引报告中检索到匹配片段，回答为提示性文案，无报告依据。"],
                    },
                }
            )
            _update_session_memory(session_id, question)
            _append_query_log(
                {
                    "ts": _utc_now_iso(),
                    "question": question,
                    "session_id": session_id,
                    "province": province,
                    "intent": intent,
                    "mode": "retrieval",
                    "empty_result": True,
                    "sources_count": 0,
                    "latency_ms": int((time.time() - started) * 1000),
                    "phase": "completed",
                }
            )
            return

        tool_answer: str | None = None
        tool_mode = ""
        tool_top_docs: list[tuple[int, dict]] = []
        try:
            if LLM_API_KEY and ENABLE_TOOL_AGENT:
                tool_answer, tool_mode, tool_top_docs = _run_tool_agent(
                    question, feedback_hint, docs, province
                )

            if tool_answer:
                answer = tool_answer
                mode = tool_mode or "tool-agent"
                src_docs = tool_top_docs if tool_top_docs else top_docs
            else:
                context = _build_agent_context(question_for_retrieval, top_docs)
                agent_answer = _call_llm_answer(question, context, feedback_hint=feedback_hint)
                answer = agent_answer or _build_structured_answer(question, top_docs, intent)
                mode = "agent" if agent_answer else "retrieval"
                src_docs = top_docs

            sources = []
            for _, doc in src_docs:
                sources.append({"province": doc["province"], "file": doc["path"]})
            answer, trust_meta = _augment_answer_for_trust(answer, src_docs)
            self._send_json({"answer": answer, "sources": sources, "mode": mode, "trust": trust_meta})
            _update_session_memory(session_id, question)
            _append_query_log(
                {
                    "ts": _utc_now_iso(),
                    "question": question,
                    "session_id": session_id,
                    "province": province,
                    "intent": intent,
                    "mode": mode,
                    "empty_result": False,
                    "sources_count": len(sources),
                    "latency_ms": int((time.time() - started) * 1000),
                    "phase": "completed",
                }
            )
        except Exception as e:
            err_msg = str(e)[:500]
            try:
                self._send_json(
                    {
                        "answer": "服务处理异常，请稍后重试。若持续出现，请检查大模型 API 与网络。",
                        "sources": [],
                        "mode": "error",
                        "trust": {
                            "evidence_strength": "none",
                            "numeric_grounding": "n/a",
                            "notes": [f"服务端异常摘要：{err_msg}"],
                        },
                    },
                    status=500,
                )
            except Exception:
                pass
            _append_query_log(
                {
                    "ts": _utc_now_iso(),
                    "question": question,
                    "session_id": session_id,
                    "province": province,
                    "intent": intent,
                    "mode": "error",
                    "empty_result": False,
                    "sources_count": 0,
                    "latency_ms": int((time.time() - started) * 1000),
                    "phase": "completed",
                    "error": err_msg,
                }
            )


def main() -> None:
    socketserver.TCPServer.allow_reuse_address = True
    if ENABLE_AUTO_TRAIN:
        t = threading.Thread(target=_auto_train_loop, name="auto-train-2am", daemon=True)
        t.start()
        print(f"已开启自动训练：每天 {AUTO_TRAIN_HOUR:02d}:00 刷新学习文件")
    with socketserver.TCPServer(("", PORT), SiteHandler) as httpd:
        url = f"http://127.0.0.1:{PORT}/index.html"
        print(f"网站根目录: {ROOT}")
        print(f"正在监听: http://127.0.0.1:{PORT}/")
        print(f"首页地址: {url}")
        print("按 Ctrl+C 停止\n")
        try:
            webbrowser.open(url)
        except OSError:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止服务。")


if __name__ == "__main__":
    main()
