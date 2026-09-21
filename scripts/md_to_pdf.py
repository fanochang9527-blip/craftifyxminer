#!/usr/bin/env python3
"""将 Markdown 文件转换为 PDF（使用 markdown + weasyprint）。"""

import sys
from pathlib import Path

import markdown
from weasyprint import HTML, CSS


def convert(md_path: str, pdf_path: str | None = None):
    md_file = Path(md_path)
    if pdf_path is None:
        pdf_path = md_file.with_suffix(".pdf")
    else:
        pdf_path = Path(pdf_path)

    md_text = md_file.read_text(encoding="utf-8")

    # Markdown -> HTML
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc"],
    )

    # 包装成完整 HTML 并注入样式
    html_full = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{md_file.stem}</title>
<style>
@page {{
    size: A4;
    margin: 2.5cm 2cm;
    @bottom-center {{
        content: counter(page);
        font-size: 9pt;
        color: #666;
    }}
}}
body {{
    font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Source Han Sans SC", "Microsoft YaHei", sans-serif;
    font-size: 10.5pt;
    line-height: 1.7;
    color: #333;
}}
h1 {{
    font-size: 20pt;
    color: #1a1a1a;
    border-bottom: 2px solid #333;
    padding-bottom: 0.3em;
    margin-top: 1.5em;
    page-break-after: avoid;
}}
h2 {{
    font-size: 14pt;
    color: #222;
    border-bottom: 1px solid #ddd;
    padding-bottom: 0.2em;
    margin-top: 1.3em;
    page-break-after: avoid;
}}
h3 {{
    font-size: 12pt;
    color: #333;
    margin-top: 1.2em;
    page-break-after: avoid;
}}
h4 {{
    font-size: 11pt;
    color: #444;
    margin-top: 1em;
}}
table {{
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
}}
th, td {{
    border: 1px solid #ccc;
    padding: 6px 8px;
    text-align: left;
}}
th {{
    background: #f5f5f5;
    font-weight: 600;
}}
tr:nth-child(even) {{
    background: #fafafa;
}}
code {{
    background: #f4f4f4;
    padding: 2px 5px;
    border-radius: 3px;
    font-family: "Consolas", "Monaco", monospace;
    font-size: 9pt;
}}
pre {{
    background: #f8f8f8;
    padding: 10px;
    border-radius: 4px;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.4;
    page-break-inside: avoid;
}}
pre code {{
    background: none;
    padding: 0;
}}
blockquote {{
    border-left: 4px solid #ddd;
    margin: 1em 0;
    padding: 0.5em 1em;
    color: #555;
    background: #f9f9f9;
}}
ul, ol {{
    margin: 0.5em 0;
    padding-left: 1.8em;
}}
li {{
    margin: 0.3em 0;
}}
a {{
    color: #0366d6;
    text-decoration: none;
}}
hr {{
    border: none;
    border-top: 1px solid #ddd;
    margin: 1.5em 0;
}}
</style>
</head>
<body>
{html_body}
</body>
</html>
"""

    HTML(string=html_full).write_pdf(str(pdf_path))
    print(f"PDF 已生成: {pdf_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.md> [output.pdf]")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
