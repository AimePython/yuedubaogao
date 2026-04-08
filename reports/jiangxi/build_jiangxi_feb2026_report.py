# -*- coding: utf-8 -*-
"""Sync 江西2月 HTML to dataflow/output、技能根目录（正文以 江西电力市场2026年2月市场运营分析报告.html 为准）。"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANON = ROOT / "江西电力市场2026年2月市场运营分析报告.html"
OUT = ROOT / "dataflow" / "output" / "江西2月市场运营分析报告.html"
SKILL = Path(r"c:\Users\wenjiel\Desktop\本家\江西\市场运营分析报告\dataflow\output\江西2月市场运营分析报告.html")
INBOX_SRC = Path(r"c:\Users\wenjiel\Desktop\市场洞察网站\江西\2月")
INBOX_DST = Path(r"c:\Users\wenjiel\Desktop\本家\江西\市场运营分析报告\dataflow\inbox")


def main():
    if not CANON.is_file():
        raise SystemExit(f"Missing {CANON}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANON, OUT)
    print("Copied ->", OUT)
    if SKILL.parent.is_dir():
        shutil.copy2(CANON, SKILL)
        print("Copied ->", SKILL)
    if INBOX_DST.is_dir() and INBOX_SRC.is_dir():
        for p in INBOX_SRC.iterdir():
            if p.is_file():
                shutil.copy2(p, INBOX_DST / p.name)
        print("Synced inbox <-", INBOX_SRC)


if __name__ == "__main__":
    main()
