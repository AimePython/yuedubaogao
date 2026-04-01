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
    q_tokens = set(_tokenize(question))
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
                    "回答使用中文，先给结论，再给2-4条依据。"
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
        answer = agent_answer or _fallback_answer(question, top_docs)
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
