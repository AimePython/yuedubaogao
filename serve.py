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
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

# 网站根目录 = 本脚本所在文件夹
ROOT = Path(__file__).resolve().parent
PORT = int(os.getenv("PORT", "8080"))
REPORTS_DIR = ROOT / "reports"


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
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
CORS_ALLOW_ORIGIN = os.getenv("CORS_ALLOW_ORIGIN", "*").strip() or "*"


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
    return "general"


def _expand_query_tokens(question: str) -> set[str]:
    tokens = set(_tokenize(question))
    for key, words in QUERY_SYNONYMS.items():
        if key in question or any(w in question for w in words):
            tokens.update(words)
    return {t.lower() for t in tokens}


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
        return "未在现有省份报告中检索到直接相关内容，请换个问法或指定省份。"
    lines = ["已从省级报告中检索到以下内容："]
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
        lines.append("现货价差结论（基于报告原文）")
        if spread_sents:
            lines.append(f"- {spread_sents[0]}")
        else:
            lines.append("- 报告未直接给出“现货价差”统一口径，以下提供可反映价差特征的原文依据。")
            for s in key_sents[:2]:
                lines.append(f"- {s}")
        return "\n".join(lines)

    if intent == "spot_low_time":
        low_time_sents = [s for s in sentences if re.search(r"(最低|低谷|谷段|时段|点|小时)", s)]
        lines.append("现货低价时段结论（基于报告原文）")
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
        lines.append("现货与中长期价格关系（基于报告原文）")
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
        lines.append("供需关系结论（基于报告原文）")
        if sd_sents:
            lines.append(f"- {sd_sents[0]}")
            for s in sd_sents[1:3]:
                lines.append(f"- {s}")
        else:
            for s in key_sents[:3]:
                lines.append(f"- {s}")
        return "\n".join(lines)

    lines.append("检索结论（基于报告原文）")
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


def _call_llm_answer(question: str, context: str) -> str | None:
    if not LLM_API_KEY:
        return None
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是电力市场报告问答助手。"
                    "只能基于给定资料回答，不确定就明确说资料不足。"
                    "回答使用中文，按以下结构回答："
                    "1) 结论；2) 关键依据(2-4条)；3) 若问题涉及最低时段/倒挂/供需，请明确指出对应判断。"
                ),
            },
            {
                "role": "user",
                "content": f"问题：{question}\n\n可用资料：\n{context}",
            },
        ],
        "temperature": 0.2,
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
        with urllib.request.urlopen(req, timeout=25) as resp:
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
                    "llm_model": LLM_MODEL if LLM_API_KEY else None,
                }
            )
            return
        if parsed.path == "/api/version":
            self._send_json({"commit": APP_COMMIT})
            return
        super().do_GET()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/ask":
            self.send_error(404, "Not Found")
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length).decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json({"error": "请求体必须是 JSON"}, status=400)
            return

        question = (payload.get("question") or "").strip()
        province = (payload.get("province") or "").strip().lower()
        if not province:
            province = _detect_province_from_question(question)
        intent = _detect_intent(question)

        if not question:
            self._send_json({"error": "question 不能为空"}, status=400)
            return

        if not _tokenize(question):
            self._send_json({"answer": "问题过短，请补充关键词后重试。", "sources": []})
            return

        docs = self._ensure_corpus()
        top_docs = _search_relevant_docs(docs, question, province, top_k=4)
        if not top_docs:
            self._send_json({"answer": _fallback_answer(question, top_docs), "sources": [], "mode": "retrieval"})
            return

        context = _build_agent_context(question, top_docs)
        agent_answer = _call_llm_answer(question, context)
        answer = agent_answer or _build_structured_answer(question, top_docs, intent)
        mode = "agent" if agent_answer else "retrieval"

        sources = []
        for _, doc in top_docs:
            sources.append({"province": doc["province"], "file": doc["path"]})
        self._send_json({"answer": answer, "sources": sources, "mode": mode})


def main() -> None:
    socketserver.TCPServer.allow_reuse_address = True
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
