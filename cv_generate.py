"""Generate a professional ATS-optimized CV PDF using ReportLab."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

BASE_DIR = Path(__file__).parent
CV_DIR = BASE_DIR / "assets" / "cv"
SOURCE_TXT = CV_DIR / "Mohammed_Basil_Yunus_Surveyor_TotalStation_2026.txt"
OUTPUT_ATS = CV_DIR / "cv.pdf"

# ATS best-practice checklist (used in dashboard)
ATS_PRINCIPLES = [
    "عمود واحد بدون جداول أو أعمدة أو صور",
    "نص قابل للنسخ والاستخراج (ليس ممسوحاً ضوئياً)",
    "عناوين أقسام قياسية: Summary, Skills, Experience, Education",
    "كلمات مفتاحية في الملخص والخبرة والمهارات",
    "أفعال إنجليزية قوية + أرقام قابلة للقياس (48 villas, 1,400+ plots)",
    "مسميات وظيفية واضحة + شركة + موقع + تواريخ",
    "خط قياسي Arial/Helvetica بحجم 10-11",
    "حجم ملف أقل من 2 MB",
    "بيانات تواصل في أعلى الصفحة",
    "ملف PDF نصي + اسم ملف احترافي",
]


def _ascii_safe(text: str) -> str:
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2022": "-",
        "\u2019": "'",
        "\u2018": "'",
        "\u00a0": " ",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r"[^\x09\x0A\x0D\x20-\x7E]", "", text)


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _parse_sections(raw: str) -> tuple[list[str], dict[str, list[str]]]:
    english = raw.split("ARABIC SUMMARY", 1)[0].strip()
    blocks = re.split(r"\n=+\n", english)
    header = [_ascii_safe(line.strip()) for line in blocks[0].splitlines() if line.strip()]

    sections: dict[str, list[str]] = {}
    for block in blocks[1:]:
        lines = [_ascii_safe(line.rstrip()) for line in block.splitlines()]
        lines = [ln for ln in lines if ln.strip()]
        if not lines:
            continue
        sections[lines[0].upper()] = lines[1:]
    return header, sections


def _join_wrapped(lines: list[str]) -> list[str]:
    merged: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            merged.append(buf.strip())
        buf = ""

    for line in lines:
        s = line.strip()
        if not s:
            flush()
            continue
        if s.startswith("- "):
            flush()
            merged.append(s)
            continue
        if re.match(r"^\d{4}", s):
            flush()
            merged.append(s)
            continue
        if not buf:
            buf = s
        elif s[0].islower() or s.startswith(","):
            buf = f"{buf} {s}"
        else:
            flush()
            buf = s
    flush()
    return merged


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "Name",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            spaceAfter=2,
            textColor=colors.HexColor("#1a1a1a"),
        ),
        "title": ParagraphStyle(
            "Title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            spaceAfter=2,
            textColor=colors.HexColor("#2c3e50"),
        ),
        "contact": ParagraphStyle(
            "Contact",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=12,
            spaceAfter=1,
            textColor=colors.HexColor("#444444"),
        ),
        "section": ParagraphStyle(
            "Section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            spaceBefore=10,
            spaceAfter=4,
            textColor=colors.HexColor("#1f4e79"),
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            spaceAfter=4,
            alignment=TA_LEFT,
        ),
        "job_title": ParagraphStyle(
            "JobTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            spaceBefore=6,
            spaceAfter=1,
        ),
        "job_org": ParagraphStyle(
            "JobOrg",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9.5,
            leading=12,
            spaceAfter=3,
            textColor=colors.HexColor("#333333"),
        ),
        "job_dates": ParagraphStyle(
            "JobDates",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=12,
            spaceAfter=3,
            textColor=colors.HexColor("#555555"),
        ),
        "label": ParagraphStyle(
            "Label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            spaceAfter=2,
        ),
    }


def _section_block(title: str, styles: dict[str, ParagraphStyle]) -> list:
    return [
        Paragraph(_escape_xml(title.upper()), styles["section"]),
        HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#1f4e79"), spaceAfter=6),
    ]


def _experience_block(lines: list[str], styles: dict[str, ParagraphStyle]) -> list:
    flow: list = []
    entries = _join_wrapped(lines)
    i = 0
    while i < len(entries):
        line = entries[i]
        if line.startswith("- "):
            flow.append(
                Paragraph(f"&bull; {_escape_xml(line[2:])}", styles["body"])
            )
            i += 1
            continue
        if i + 2 < len(entries) and re.match(r"^\d{4}", entries[i + 2]):
            title, org, dates = entries[i], entries[i + 1], entries[i + 2]
            flow.append(
                Paragraph(
                    f"<b>{_escape_xml(title)}</b> &nbsp;|&nbsp; {_escape_xml(dates)}",
                    styles["job_title"],
                )
            )
            flow.append(Paragraph(_escape_xml(org), styles["job_org"]))
            i += 3
            continue
        flow.append(Paragraph(_escape_xml(line), styles["body"]))
        i += 1
    return flow


def _skills_block(lines: list[str], styles: dict[str, ParagraphStyle]) -> list:
    flow: list = []
    for line in _join_wrapped(lines):
        if ":" in line:
            label, value = line.split(":", 1)
            flow.append(
                Paragraph(
                    f"<b>{_escape_xml(label.strip())}:</b> {_escape_xml(value.strip())}",
                    styles["body"],
                )
            )
        else:
            flow.append(Paragraph(_escape_xml(line), styles["body"]))
    return flow


def _simple_block(lines: list[str], styles: dict[str, ParagraphStyle]) -> list:
    flow: list = []
    for line in _join_wrapped(lines):
        if line.startswith("- "):
            flow.append(Paragraph(f"&bull; {_escape_xml(line[2:])}", styles["body"]))
        elif ":" in line and len(line.split(":", 1)[0]) < 35:
            label, value = line.split(":", 1)
            flow.append(
                Paragraph(
                    f"<b>{_escape_xml(label.strip())}:</b> {_escape_xml(value.strip())}",
                    styles["body"],
                )
            )
        else:
            flow.append(Paragraph(_escape_xml(line), styles["body"]))
    return flow


def generate_ats_pdf(
    source_txt: Path = SOURCE_TXT,
    output_pdf: Path = OUTPUT_ATS,
    backup: bool = True,
) -> Path:
    if not source_txt.exists():
        raise FileNotFoundError(f"ملف المصدر غير موجود: {source_txt}")

    raw = source_txt.read_text(encoding="utf-8")
    header, sections = _parse_sections(raw)
    styles = _styles()

    if backup and output_pdf.exists():
        shutil.copy2(output_pdf, output_pdf.with_suffix(".pdf.bak"))

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Mohammed Basil Yunus - General Land Surveyor CV",
        author="Mohammed Basil Mahmood Yunus",
    )

    story: list = []

    if header:
        story.append(Paragraph(_escape_xml(header[0]), styles["name"]))
        if len(header) > 1:
            story.append(Paragraph(_escape_xml(header[1]), styles["title"]))
        for line in header[2:]:
            story.append(Paragraph(_escape_xml(line), styles["contact"]))
        story.append(Spacer(1, 4))

    renderers = {
        "PROFESSIONAL SUMMARY": _simple_block,
        "CORE SKILLS": _skills_block,
        "PROFESSIONAL EXPERIENCE": _experience_block,
    }

    for title, lines in sections.items():
        story.extend(_section_block(title, styles))
        renderer = renderers.get(title, _simple_block)
        story.extend(renderer(lines, styles))

    doc.build(story)
    return output_pdf


if __name__ == "__main__":
    path = generate_ats_pdf()
    print(f"Generated: {path} ({path.stat().st_size // 1024} KB)")
