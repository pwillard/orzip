#!/usr/bin/env python
"""Build the ORZIP PDF user guide from Markdown using ReportLab."""
from __future__ import annotations

import argparse
import html
import os
import re
import tempfile
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

VERSION = "1.0.4"


class InvariantCanvas(canvas.Canvas):
    """ReportLab canvas with deterministic metadata and document IDs."""

    def __init__(self, *args, **kwargs):
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)


def inline_markup(text: str, mono_font: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", rf'<font name="{mono_font}">\1</font>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    return escaped


def parse_table(lines: list[str], mono_font: str, styles: dict[str, ParagraphStyle]):
    rows: list[list[Paragraph]] = []
    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if index == 1 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        style = styles["table_header"] if not rows else styles["table_cell"]
        rows.append([Paragraph(inline_markup(cell, mono_font), style) for cell in cells])

    columns = max(len(row) for row in rows)
    for row in rows:
        row.extend(Paragraph("", styles["table_cell"]) for _ in range(columns - len(row)))
    available = 7.0 * inch
    if columns == 2:
        widths = [1.65 * inch, available - 1.65 * inch]
    elif columns == 3:
        widths = [1.0 * inch, available - 2.15 * inch, 1.15 * inch]
    else:
        widths = [available / columns] * columns
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6F1")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17365D")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9AA7B4")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def markdown_story(source: Path, mono_font: str):
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "ORZIPTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=27,
            textColor=colors.HexColor("#17365D"),
            alignment=TA_CENTER,
            spaceAfter=18,
        ),
        "h2": ParagraphStyle(
            "ORZIPHeading2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=colors.HexColor("#1F4E79"),
            spaceBefore=12,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "ORZIPHeading3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#2F5597"),
            spaceBefore=9,
            spaceAfter=5,
            keepWithNext=False,
        ),
        "body": ParagraphStyle(
            "ORZIPBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "ORZIPBullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            leftIndent=16,
            firstLineIndent=-8,
            spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "ORZIPCode",
            parent=base["Code"],
            fontName=mono_font,
            fontSize=7.2,
            leading=9.3,
            leftIndent=8,
            rightIndent=8,
            borderWidth=0.5,
            borderColor=colors.HexColor("#C9D2DC"),
            borderPadding=7,
            backColor=colors.HexColor("#F4F6F8"),
            spaceBefore=4,
            spaceAfter=8,
            splitLongWords=True,
        ),
        "table_header": ParagraphStyle(
            "ORZIPTableHeader", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8, leading=10
        ),
        "table_cell": ParagraphStyle(
            "ORZIPTableCell", parent=base["BodyText"], fontName="Helvetica", fontSize=7.8, leading=10
        ),
    }

    lines = source.read_text(encoding="utf-8").splitlines()
    story = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            text = " ".join(part.strip() for part in paragraph)
            story.append(Paragraph(inline_markup(text, mono_font), styles["body"]))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            code = "<br/>".join(html.escape(part, quote=False) if part else "&nbsp;" for part in code_lines)
            story.append(Paragraph(code, styles["code"]))
        elif stripped.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[2:], mono_font), styles["title"]))
            story.append(Paragraph("Windows command-line guide", ParagraphStyle("Subtitle", parent=styles["body"], alignment=TA_CENTER, textColor=colors.HexColor("#666666"), spaceAfter=14)))
        elif stripped.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[3:], mono_font), styles["h2"]))
        elif stripped.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[4:], mono_font), styles["h3"]))
        elif stripped.startswith("|"):
            flush_paragraph()
            table_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            story.append(parse_table(table_lines, mono_font, styles))
            story.append(Spacer(1, 8))
            continue
        elif re.match(r"^[-*]\s+", stripped):
            flush_paragraph()
            story.append(Paragraph("• " + inline_markup(stripped[2:], mono_font), styles["bullet"]))
        elif re.match(r"^\d+\.\s+", stripped):
            flush_paragraph()
            number, item = stripped.split(". ", 1)
            story.append(Paragraph(f"{number}. " + inline_markup(item, mono_font), styles["bullet"]))
        elif stripped == "":
            flush_paragraph()
        elif stripped == "---":
            flush_paragraph()
            story.append(Spacer(1, 5))
        else:
            paragraph.append(stripped)
        index += 1

    flush_paragraph()
    return story


def draw_page(canvas, document) -> None:
    canvas.saveState()
    width, height = LETTER
    canvas.setStrokeColor(colors.HexColor("#D0D7DE"))
    canvas.setLineWidth(0.5)
    canvas.line(0.7 * inch, 0.55 * inch, width - 0.7 * inch, 0.55 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#5A6570"))
    canvas.drawString(0.7 * inch, 0.35 * inch, f"ORZIP {VERSION} User Guide")
    canvas.drawRightString(width - 0.7 * inch, 0.35 * inch, f"Page {document.page}")
    canvas.restoreState()


def build_pdf(source: Path, output: Path) -> Path:
    mono_font = "Courier"

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.stem}-", suffix=".pdf", dir=output.parent)
    os.close(fd)
    temp_output = Path(temp_name)
    try:
        document = SimpleDocTemplate(
            str(temp_output),
            pagesize=LETTER,
            rightMargin=0.7 * inch,
            leftMargin=0.7 * inch,
            topMargin=0.65 * inch,
            bottomMargin=0.72 * inch,
            title=f"ORZIP {VERSION} User Guide",
            author="ORZIP",
            subject="MSTS/Open Rails shape file conversion and validation",
        )
        document.build(
            markdown_story(source, mono_font),
            onFirstPage=draw_page,
            onLaterPages=draw_page,
            canvasmaker=InvariantCanvas,
        )
        try:
            os.replace(temp_output, output)
        except OSError as exc:
            raise RuntimeError(f"PDF built, but final output could not be replaced: {exc}\nFresh PDF: {temp_output}") from exc
        return output
    except Exception:
        if temp_output.exists() and temp_output.stat().st_size == 0:
            temp_output.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", default=Path("USER_GUIDE.md"))
    parser.add_argument("-o", "--output", type=Path, default=Path("DIST/DOCS/ORZIP_EXE_User_Guide.pdf"))
    args = parser.parse_args()
    result = build_pdf(args.source.resolve(), args.output.resolve())
    print(f"Built {result} ({result.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
