from io import BytesIO
from pathlib import Path
import re
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from .calendar import calendar_info
from .accounting import money


def invoice_pdf(tenant, doc, contact):
    buffer = BytesIO()
    font = "Helvetica"
    latin_path = Path(__file__).parent / "assets" / "NotoSans.ttf"
    if latin_path.exists():
        if "HisaabLatin" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("HisaabLatin", str(latin_path), shapable=False))
        font = "HisaabLatin"
    font_path = Path(__file__).parent / "assets" / "NotoSansDevanagari.ttf"
    if font_path.exists():
        if "Hisaab" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("Hisaab", str(font_path), shapable=True))
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName, style.fontSize, style.leading = font, 10, 16
    styles.add(ParagraphStyle("Company", fontName=font, fontSize=22, leading=30, textColor=colors.HexColor("#242e2b")))
    styles.add(ParagraphStyle("SmallMuted", fontName=font, fontSize=9, leading=14, textColor=colors.HexColor("#5d6662")))
    styles.add(ParagraphStyle("Amount", fontName=font, fontSize=14, leading=22, alignment=TA_RIGHT))
    def p(value, style="Normal"):
        value = escape(str(value)).replace("\n", "<br/>")
        # The Devanagari face does not contain Latin letters. Keep Latin in the
        # base font and shape each Nepali word with the embedded script face.
        if font_path.exists():
            value = re.sub(r"([\u0900-\u097f\u200c\u200d]+)", lambda match: '<font name="Hisaab">' + match.group(0) + '</font>', value)
        return Paragraph(value, styles[style])
    info = calendar_info(str(doc.date))
    story = [p(tenant.name, "Company"), p(tenant.address or "Nepal", "SmallMuted")]
    if tenant.pan:
        story.append(p(f"PAN: {tenant.pan}", "SmallMuted"))
    title = "Tax invoice" if doc.payload.get("tax_invoice") else "Internal transaction record"
    story += [Spacer(1, 20), p(title, "Heading1"), p(f"{doc.number or 'Draft'} | {doc.kind.replace('_', ' ').title()}"), p(f"AD {info['ad']}   BS {info['bs']}   Fiscal year {info['fiscal_year']}", "SmallMuted"), Spacer(1, 18)]
    if contact:
        story += [p(contact.name, "Heading2"), p(contact.address or ""), p(f"PAN: {contact.pan or 'Not supplied'}", "SmallMuted"), Spacer(1, 18)]
    rows = [[p("Product"), p("Quantity"), p("Rate (NPR)"), p("Net (NPR)"), p("Total (NPR)")]]
    for line in doc.payload.get("lines", []):
        rows.append([p(line.get("name", "")), p(f"{line['quantity']} {line.get('unit', '')}"), p(money(line.get("unit_price", 0))), p(money(line.get("net", 0))), p(money(line.get("total", 0)))])
    if len(rows) > 1:
        table = Table(rows, colWidths=[185, 80, 75, 75, 95], repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1ef")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#ccd2ce")), ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#e0e4e1")), ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        story.append(table)
    story += [Spacer(1, 20), p(f"Total NPR {money(doc.total)}", "Amount"), Spacer(1, 12)]
    if doc.payload.get("notes"):
        story.append(p(doc.payload["notes"]))
    if not doc.payload.get("tax_invoice"):
        story += [Spacer(1, 24), p("For internal accounting only. This is not an approved VAT/tax invoice. Tax billing is disabled until applicable IRD requirements are verified.", "SmallMuted")]
    def footer(canvas, document):
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#5d6662"))
        canvas.drawString(42, 28, f"Hisaab | {doc.number or 'Draft'}")
        canvas.drawRightString(A4[0] - 42, 28, f"Page {document.page}")
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=42, rightMargin=42, topMargin=38, bottomMargin=48, title=doc.number or "Draft", author=tenant.name).build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
