#!/usr/bin/env python3
"""将 Markdown 文件转换为精美 HTML（便于浏览器打印为 PDF）。"""

import sys
from pathlib import Path

import markdown


def convert(md_path: str, html_path: str | None = None):
    md_file = Path(md_path)
    if html_path is None:
        html_path = md_file.with_suffix(".html")
    else:
        html_path = Path(html_path)

    md_text = md_file.read_text(encoding="utf-8")

    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc"],
    )

    html_full = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{md_file.stem}</title>
<style>
@page {{ size: A4; margin: 2cm 1.8cm; }}
* {{ box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC",
                 "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 10.5pt;
    line-height: 1.75;
    color: #333;
    max-width: 900px;
    margin: 0 auto;
    padding: 2em;
}}
h1 {{
    font-size: 22pt;
    color: #1a1a1a;
    border-bottom: 2.5px solid #2c3e50;
    padding-bottom: 0.3em;
    margin-top: 0;
    page-break-after: avoid;
}}
h2 {{
    font-size: 15pt;
    color: #222;
    border-bottom: 1px solid #ddd;
    padding-bottom: 0.25em;
    margin-top: 1.8em;
    page-break-after: avoid;
}}
h3 {{
    font-size: 12.5pt;
    color: #333;
    margin-top: 1.5em;
    page-break-after: avoid;
}}
h4 {{
    font-size: 11pt;
    color: #444;
    margin-top: 1.2em;
}}
table {{
    border-collapse: collapse;
    width: 100%;
    margin: 1.2em 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
}}
th, td {{
    border: 1px solid #ccc;
    padding: 7px 10px;
    text-align: left;
    vertical-align: top;
}}
th {{
    background: #f0f2f5;
    font-weight: 600;
    color: #1a1a1a;
}}
tr:nth-child(even) {{ background: #fafbfc; }}
code {{
    background: #f4f4f5;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: "SF Mono", "Consolas", "Monaco", monospace;
    font-size: 9pt;
    color: #c7254e;
}}
pre {{
    background: #f8f9fa;
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.5;
    border: 1px solid #e8e8e8;
    page-break-inside: avoid;
}}
pre code {{
    background: none;
    padding: 0;
    color: #333;
}}
blockquote {{
    border-left: 4px solid #2c3e50;
    margin: 1.2em 0;
    padding: 0.6em 1.2em;
    color: #555;
    background: #f8f9fa;
    border-radius: 0 4px 4px 0;
}}
ul, ol {{
    margin: 0.6em 0;
    padding-left: 2em;
}}
li {{
    margin: 0.35em 0;
}}
a {{
    color: #0366d6;
    text-decoration: none;
}}
hr {{
    border: none;
    border-top: 1px solid #e1e4e8;
    margin: 2em 0;
}}
@media print {{
    body {{ padding: 0; }}
    h1, h2, h3 {{ page-break-after: avoid; }}
    table, pre, blockquote {{ page-break-inside: avoid; }}
}}
</style>
</head>
<body>
{html_body}
</body>
</html>
"""

    html_path.write_text(html_full, encoding="utf-8")
    print(f"HTML 已生成: {html_path}")
    print("提示: 用浏览器打开后按 Ctrl+P → 目标打印机选择「另存为 PDF」即可导出 PDF。")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.md> [output.html]")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
