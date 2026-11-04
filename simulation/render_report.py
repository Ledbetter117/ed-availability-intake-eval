"""Render a Markdown technical report to a readable, reproducible PDF.

Optional publication dependency: reportlab. Core evaluation code needs no renderer.
Usage: python render_paper.py source.md output.pdf
"""
from pathlib import Path
import argparse
import html
import re
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Preformatted, Table, TableStyle, Image as ReportImage,
)


def inline(value):
    value = html.escape(value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: (
        '<link href="' + m[2] + '" color="#355a64">' + m[1] + '</link>'
        if m[2].startswith(('https://', 'http://')) else m[1] + ' (' + m[2] + ')'
    ), value)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier" size="8">\1</font>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r'<b>\1</b>', value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r'<i>\1</i>', value)
    # Base fonts render these reliably; preserve scientific symbols and Unicode in source.
    return value.replace('→', '-&gt;').replace('×', ' x ').replace('–', '-').replace('—', ' - ')


def build(source, destination):
    lines = source.read_text(encoding='utf-8-sig').splitlines()
    title = next((s[2:] for s in lines if s.startswith('# ')), source.stem)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('PaperBody', fontName='Helvetica', fontSize=10,
                              leading=14.5, spaceAfter=8, splitLongWords=True))
    styles.add(ParagraphStyle('PaperTitle', fontName='Helvetica-Bold', fontSize=20,
                              leading=24, textColor=colors.HexColor('#203a3e'), spaceAfter=16))
    styles.add(ParagraphStyle('PaperH1', fontName='Helvetica-Bold', fontSize=13,
                              leading=17, spaceBefore=13, spaceAfter=8, keepWithNext=True))
    styles.add(ParagraphStyle('PaperH2', fontName='Helvetica-Bold', fontSize=11,
                              leading=15, spaceBefore=10, spaceAfter=7, keepWithNext=True))
    styles.add(ParagraphStyle('PaperCell', fontName='Helvetica', fontSize=8,
                              leading=10.5, spaceAfter=0, splitLongWords=True))
    styles.add(ParagraphStyle('PaperCaption', parent=styles['PaperBody'], keepWithNext=True))
    styles.add(ParagraphStyle('PaperCode', fontName='Courier', fontSize=7,
                              leading=9, spaceAfter=10, backColor=colors.HexColor('#f0f3f2')))
    body, para, table_rows, code = [], [], [], []
    in_code = False
    def flush_para():
        if para:
            body.append(Paragraph(inline(' '.join(para)), styles['PaperBody']))
            para.clear()
    def flush_table():
        if not table_rows:
            return
        count = max(map(len, table_rows))
        cells = [[Paragraph(inline(c), styles['PaperCell']) for c in row] for row in table_rows]
        width = 7.05 * inch / count
        t = Table(cells, colWidths=[width] * count, repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e5ece8')),
            ('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6), ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LINEBELOW', (0,0), (-1,0), .7, colors.HexColor('#77938c')),
            ('LINEBELOW', (0,1), (-1,-1), .3, colors.HexColor('#d4ddd9')),
        ]))
        body.extend([t, Spacer(1, 10)])
        table_rows.clear()
    for line in lines:
        picture = re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', line.strip())
        if picture:
            flush_para(); flush_table()
            candidate = (source.parent / picture[2]).resolve()
            if not candidate.is_relative_to(source.parent.parent.resolve()) or candidate.suffix.lower() != '.png':
                raise ValueError('Report figure must be a local PNG within the publication root')
            from PIL import Image as PillowImage
            with PillowImage.open(candidate, formats=('PNG',)) as figure:
                width, height = figure.size
                if width * height > 10000000:
                    raise ValueError('Report figure exceeds pixel limit')
            graphic = ReportImage(str(candidate), width=7.0*inch, height=7.0*inch*height/width)
            graphic.keepWithNext = True
            body.append(graphic)
            continue
        if line.startswith('```'):
            flush_para(); flush_table()
            if in_code:
                body.append(Preformatted('\n'.join(code), styles['PaperCode'], maxLineLength=97))
                code.clear()
            in_code = not in_code
            continue
        if in_code:
            code.append(line); continue
        if line.startswith('|'):
            flush_para()
            row = [s.strip() for s in line.strip().strip('|').split('|')]
            if not all(re.fullmatch(r'[:\s-]+', c) for c in row):
                table_rows.append(row)
            continue
        flush_table()
        if not line.strip() or line.strip() in ('---', '***'):
            flush_para(); continue
        if re.match(r'^Table \d+\.', line):
            flush_para()
            body.append(Paragraph(inline(line), styles['PaperCaption']))
        elif line.startswith('#'):
            flush_para()
            level = len(line) - len(line.lstrip('#'))
            body.append(Paragraph(inline(line[level:].strip()), styles[
                'PaperTitle' if level == 1 else 'PaperH1' if level == 2 else 'PaperH2']))
        elif re.match(r'^\s*(?:[-*]|\d+\.)\s+', line):
            flush_para()
            body.append(Paragraph(inline(line.strip()), styles['PaperBody']))
        else:
            para.append(line.lstrip('> ').strip())
    flush_para(); flush_table()
    if in_code:
        raise ValueError('Unclosed Markdown code fence')
    destination.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(destination), pagesize=(8.5*inch, 11*inch),
                            rightMargin=.72*inch, leftMargin=.72*inch,
                            topMargin=.65*inch, bottomMargin=.65*inch,
                            title=title, author='Galen Coulter-Ledbetter')
    def footer(canvas, _doc):
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#5d6868'))
        canvas.drawString(.72*inch, .35*inch, 'Technical report | synthetic evaluation | November 2026')
        canvas.drawRightString(7.78*inch, .35*inch, str(canvas.getPageNumber()))
    doc.build(body, onFirstPage=footer, onLaterPages=footer)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    build(args.source, args.destination)
    print(args.destination)
