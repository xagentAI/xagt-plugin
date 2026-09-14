"""把 docs/walkthrough/ 下按 NN- 编号的分册合并排版成一份 Word 讲义（可再转 PDF）。

运行：.venv/Scripts/python.exe scripts/build_walkthrough_docx.py
设计：内容全部来自已有 markdown，脚本只负责解析与排版，不新增正文事实。
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "docs" / "walkthrough"
OUT_DIR = ROOT / "docs" / "exports"
OUT_DOCX = OUT_DIR / "YAI-Agent-Core-源码逐行讲解.docx"

# 自动收录所有 NN- 开头的分册并按编号排序，新增章节无需改本脚本
CHAPTERS = sorted(p.name for p in SRC_DIR.glob("[0-9][0-9]-*.md"))


# ---------- 样式工具 ----------

def set_east_asian(style, ascii_font: str, ea_font: str, size: Pt,
                   bold: bool | None = None, color: str = "1A1B1C") -> None:
    style.font.name = ascii_font
    style.font.size = size
    style.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        style.font.bold = bold
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), ascii_font)
    rfonts.set(qn("w:hAnsi"), ascii_font)
    rfonts.set(qn("w:eastAsia"), ea_font)


def shade_paragraph(par, fill: str) -> None:
    ppr = par._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    ppr.append(shd)


def shade_run(run, fill: str) -> None:
    rpr = run._r.get_or_add_rPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    rpr.append(shd)


def preserve_spaces(run) -> None:
    t = run._r.find(qn("w:t"))
    if t is not None:
        t.set(qn("xml:space"), "preserve")


_INLINE = re.compile(r"(\*\*.+?\*\*|`.+?`|\[[^\]]+\]\([^)]+\))")


def add_inline(par, text: str, *, base_size: Pt | None = None) -> None:
    """解析 **粗体**、`行内代码`、[链接](url)。"""
    for token in _INLINE.split(text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            run = par.add_run(token[2:-2])
            run.bold = True
        elif token.startswith("`") and token.endswith("`"):
            run = par.add_run(token[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(10.5)
            rpr = run._r.get_or_add_rPr()
            rfonts = OxmlElement("w:rFonts")
            rfonts.set(qn("w:ascii"), "Consolas")
            rfonts.set(qn("w:hAnsi"), "Consolas")
            rfonts.set(qn("w:eastAsia"), "宋体")
            rpr.append(rfonts)
            shade_run(run, "F2F2F2")
        elif token.startswith("[") and "](" in token:
            label, url = token[1:].split("](", 1)
            run = par.add_run(f"{label}（{url[:-1]}）")
            run.font.color.rgb = RGBColor.from_string("1F4E79")
        else:
            run = par.add_run(token)
        if base_size is not None:
            run.font.size = base_size
        preserve_spaces(run)


# ---------- Markdown 分块解析 ----------

def _is_block_start(line: str) -> bool:
    return (
        line.startswith("```")
        or bool(re.match(r"^#{1,4} ", line))
        or line.startswith("|")
        or line.startswith(">")
        or bool(re.match(r"^[-*] ", line))
        or bool(re.match(r"^\d+\.\s", line))
        or line.strip() in ("---", "")
    )


def parse_md(text: str) -> list[tuple[str, object]]:
    blocks: list[tuple[str, object]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            buf: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(("code", "\n".join(buf)))
            continue
        m = re.match(r"^(#{1,4}) ", line)
        if m:
            blocks.append((f"h{len(m.group(1))}", line[len(m.group(0)):].strip()))
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            blocks.append(("table", rows))
            continue
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            blocks.append(("quote", " ".join(buf)))
            continue
        if re.match(r"^[-*] ", line):
            items = []
            while i < len(lines) and re.match(r"^[-*] ", lines[i]):
                items.append(lines[i][2:])
                i += 1
            blocks.append(("ul", items))
            continue
        if re.match(r"^\d+\.\s", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i]):
                items.append(re.sub(r"^\d+\.\s", "", lines[i]))
                i += 1
            blocks.append(("ol", items))
            continue
        if line.strip() in ("---", ""):
            i += 1
            continue
        buf = [line]
        i += 1
        while i < len(lines) and not _is_block_start(lines[i]):
            buf.append(lines[i])
            i += 1
        blocks.append(("p", " ".join(buf)))
    return blocks


def parse_table(rows: list[str]) -> tuple[list[str], list[list[str]]]:
    matrix = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    header = matrix[0]
    body = [r for r in matrix[2:]]  # 第二行是 --- 分隔行
    return header, body


# ---------- docx 构建 ----------

def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = Document()

    # 页面：A4 + 2.5cm
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.5)
    sec.left_margin = sec.right_margin = Cm(2.5)

    # 样式
    normal = doc.styles["Normal"]
    set_east_asian(normal, "Arial", "宋体", Pt(12))
    normal.paragraph_format.line_spacing = 1.5
    ppr = normal.element.get_or_add_pPr()
    ind = OxmlElement("w:ind")
    ind.set(qn("w:firstLineChars"), "200")
    ppr.append(ind)

    for name, size in (("Heading 1", 16), ("Heading 2", 14), ("Heading 3", 12)):
        st = doc.styles[name]
        set_east_asian(st, "Arial", "黑体", Pt(size), bold=True, color="000000")
    title_style = doc.styles["Title"]
    set_east_asian(title_style, "Arial", "黑体", Pt(22), bold=True)
    # 去掉默认 Title 样式的蓝色下划线边框
    title_ppr = title_style.element.get_or_add_pPr()
    title_bdr = title_ppr.find(qn("w:pBdr"))
    if title_bdr is not None:
        title_ppr.remove(title_bdr)

    # 打开时自动更新域（让 Word/LibreOffice 生成目录页码）
    update_fields = OxmlElement("w:updateFields")
    update_fields.set(qn("w:val"), "true")
    doc.settings.element.append(update_fields)

    # 取 List Number 样式背后的抽象编号，供每个有序列表独立从 1 开始
    numbering_el = doc.part.numbering_part.element
    ln_numpr = doc.styles["List Number"].element.find(qn("w:pPr")).find(qn("w:numPr"))
    base_num_id = int(ln_numpr.find(qn("w:numId")).get(qn("w:val")))
    base_num = next(
        n for n in numbering_el.findall(qn("w:num"))
        if int(n.get(qn("w:numId"))) == base_num_id
    )
    abstract_num_id = int(base_num.find(qn("w:abstractNumId")).get(qn("w:val")))

    def new_restart_num_id() -> int:
        existing = [int(n.get(qn("w:numId"))) for n in numbering_el.findall(qn("w:num"))]
        num_id = max(existing) + 1
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), str(num_id))
        aref = OxmlElement("w:abstractNumId")
        aref.set(qn("w:val"), str(abstract_num_id))
        num.append(aref)
        override = OxmlElement("w:lvlOverride")
        override.set(qn("w:ilvl"), "0")
        start = OxmlElement("w:startOverride")
        start.set(qn("w:val"), "1")
        override.append(start)
        num.append(override)
        numbering_el.append(num)
        return num_id

    code_style = doc.styles.add_style("CodeBlock", WD_STYLE_TYPE.PARAGRAPH)
    code_style.base_style = doc.styles["Normal"]
    set_east_asian(code_style, "Consolas", "宋体", Pt(10))
    code_style.paragraph_format.line_spacing = 1.15
    code_style.paragraph_format.left_indent = Cm(0.4)
    code_style.paragraph_format.space_before = Pt(0)
    code_style.paragraph_format.space_after = Pt(0)
    cpr = code_style.element.get_or_add_pPr()
    cind = OxmlElement("w:ind")
    cind.set(qn("w:firstLine"), "0")
    cind.set(qn("w:firstLineChars"), "0")
    cpr.append(cind)

    quote_style = doc.styles.add_style("QuoteBlock", WD_STYLE_TYPE.PARAGRAPH)
    quote_style.base_style = doc.styles["Normal"]
    set_east_asian(quote_style, "Arial", "楷体", Pt(11), color="444444")
    quote_style.paragraph_format.left_indent = Cm(0.6)
    qpr = quote_style.element.get_or_add_pPr()
    qind = OxmlElement("w:ind")
    qind.set(qn("w:firstLine"), "0")
    qpr.append(qind)

    # ---- 封面 ----
    for _ in range(5):
        doc.add_paragraph()
    t = doc.add_paragraph(style="Title")
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t.add_run("YAI Agent Core\n源码逐行讲解")
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("00–14 分册合订 · 边学边造配套讲义")
    r.font.size = Pt(13)
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_text = (
        "对应代码主线（MCP Client · OpenAPI 发现 · SQLite 持久化记忆）"
        "　|　Gi-Tuu　|　2026-09"
    )
    r = meta.add_run(meta_text)
    r.font.size = Pt(10.5)
    r.font.color.rgb = RGBColor.from_string("666666")

    # ---- 目录（独立一节）----
    doc.add_section(WD_SECTION.NEW_PAGE)
    toc_title = doc.add_paragraph()
    tt_run = toc_title.add_run("目录")
    tt_run.bold = True
    tt_run.font.size = Pt(16)
    rpr = tt_run._r.get_or_add_rPr()
    rf = OxmlElement("w:rFonts")
    rf.set(qn("w:ascii"), "Arial")
    rf.set(qn("w:hAnsi"), "Arial")
    rf.set(qn("w:eastAsia"), "黑体")
    rpr.append(rf)
    toc_par = doc.add_paragraph()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-2" \\h \\z \\u '
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    hint = OxmlElement("w:t")
    hint.text = "（在 Word 中右键此处选择“更新域”即可生成带页码目录）"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run_el = toc_par.add_run()._r
    for el in (fld_begin, instr, fld_sep, hint, fld_end):
        run_el.append(el)

    # ---- 正文（独立一节，页码从 1 开始）----
    body_section = doc.add_section(WD_SECTION.NEW_PAGE)
    body_section.footer.is_linked_to_previous = False
    footer_par = body_section.footer.paragraphs[0]
    footer_par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fb = OxmlElement("w:fldChar")
    fb.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = " PAGE "
    fe = OxmlElement("w:fldChar")
    fe.set(qn("w:fldCharType"), "end")
    fr = footer_par.add_run()._r
    for el in (fb, it, fe):
        fr.append(el)
    pgnum = OxmlElement("w:pgNumType")
    pgnum.set(qn("w:start"), "1")
    body_section._sectPr.append(pgnum)

    def render_blocks(blocks: list[tuple[str, object]]) -> None:
        for kind, payload in blocks:
            if kind.startswith("h"):
                doc.add_paragraph(str(payload), style=f"Heading {kind[1]}")
            elif kind == "p":
                par = doc.add_paragraph()
                add_inline(par, str(payload))
            elif kind == "quote":
                par = doc.add_paragraph(style="QuoteBlock")
                add_inline(par, str(payload))
            elif kind == "ul":
                for item in payload:  # type: ignore[assignment]
                    par = doc.add_paragraph(style="List Bullet")
                    add_inline(par, item)
            elif kind == "ol":
                num_id = new_restart_num_id()
                for item in payload:  # type: ignore[assignment]
                    par = doc.add_paragraph(style="List Number")
                    ppr = par._p.get_or_add_pPr()
                    numpr = OxmlElement("w:numPr")
                    ilvl = OxmlElement("w:ilvl")
                    ilvl.set(qn("w:val"), "0")
                    nid = OxmlElement("w:numId")
                    nid.set(qn("w:val"), str(num_id))
                    numpr.append(ilvl)
                    numpr.append(nid)
                    ppr.append(numpr)
                    add_inline(par, item)
            elif kind == "code":
                for code_line in str(payload).split("\n"):
                    par = doc.add_paragraph(style="CodeBlock")
                    run = par.add_run(code_line if code_line else " ")
                    preserve_spaces(run)
                    shade_paragraph(par, "F4F5F7")
            elif kind == "table":
                header, body = parse_table(payload)  # type: ignore[arg-type]
                table = doc.add_table(rows=1, cols=len(header))
                table.style = "Table Grid"
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                hdr = table.rows[0].cells
                for j, h in enumerate(header):
                    hdr[j].text = ""
                    run = hdr[j].paragraphs[0].add_run(h)
                    run.bold = True
                    run.font.size = Pt(10.5)
                    tcpr = hdr[j]._tc.get_or_add_tcPr()
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear")
                    shd.set(qn("w:fill"), "D9D9D9")
                    tcpr.append(shd)
                for row in body:
                    cells = table.add_row().cells
                    for j, val in enumerate(row):
                        if j >= len(cells):
                            break
                        cells[j].text = ""
                        add_inline(cells[j].paragraphs[0], val, base_size=Pt(10.5))
                doc.add_paragraph()

    for idx, fname in enumerate(CHAPTERS):
        text = (SRC_DIR / fname).read_text(encoding="utf-8")
        render_blocks(parse_md(text))
        if idx != len(CHAPTERS) - 1:
            doc.add_page_break()

    doc.save(OUT_DOCX)
    print(f"saved: {OUT_DOCX}")


if __name__ == "__main__":
    build()
