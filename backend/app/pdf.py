"""Minimal tabular PDF rendering with reportlab."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def table_pdf(title: str, subtitle: str, headers: list[str], rows: list[list[str]], footer_rows: list[list[str]] | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Paragraph(subtitle, styles["Normal"]), Spacer(1, 12)]
    data = [headers] + rows + (footer_rows or [])
    t = Table(data, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
        ("ALIGN", (-3, 1), (-1, -1), "RIGHT"),
    ]
    if footer_rows:
        style += [("FONTNAME", (0, -len(footer_rows)), (-1, -1), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    story.append(t)
    doc.build(story)
    return buf.getvalue()
