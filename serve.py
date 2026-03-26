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
import socketserver
import webbrowser
from pathlib import Path

# 网站根目录 = 本脚本所在文件夹
ROOT = Path(__file__).resolve().parent
PORT = 8080


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
