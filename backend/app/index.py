from collections import defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
import unicodedata
from xml.sax.saxutils import escape

from pydantic import BaseModel, Field, model_validator
from typing import Literal
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


class IndexRequest(BaseModel):
    start: int = Field(ge=0, le=2147483647)
    end: int = Field(ge=0, le=2147483647)
    groups: list[Literal['tags', 'correspondent']] = Field(default_factory=list, max_length=2)
    sort: Literal['title', 'asn', 'date'] = 'title'
    title: str = Field(default='Archivverzeichnis', min_length=1, max_length=150)

    @model_validator(mode='after')
    def validate_range(self):
        if self.end < self.start:
            raise ValueError('Die ASN bis muss mindestens so groß wie die ASN von sein.')
        if len(set(self.groups)) != len(self.groups):
            raise ValueError('Eine Gruppierung darf nur einmal vorkommen.')
        return self


def alphabetical(value):
    value = str(value).casefold().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
    return ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))


def build_index(documents, tags, correspondents, request):
    tag_names = {t['id']: t['name'] for t in tags}
    correspondent_names = {c['id']: c['name'] for c in correspondents}
    docs = []
    for doc in documents:
        asn = doc.get('archive_serial_number')
        if asn is None or not request.start <= asn <= request.end:
            continue
        docs.append({
            'id': doc['id'], 'asn': asn, 'title': doc.get('title') or 'Ohne Titel',
            'date': (doc.get('created') or '')[:10],
            'tags': sorted({tag_names.get(t, f'Tag #{t}') for t in doc.get('tags', [])}, key=alphabetical),
            'correspondent': correspondent_names.get(doc.get('correspondent'), 'Ohne Korrespondent'),
        })
    key = {'title': lambda d: (alphabetical(d['title']), d['asn']),
           'asn': lambda d: (d['asn'], alphabetical(d['title'])),
           'date': lambda d: (d['date'], d['asn'])}[request.sort]

    def group(items, depth=0, path=()):
        if depth == len(request.groups):
            return [{'path': list(path), 'documents': sorted(items, key=key)}]
        buckets = defaultdict(list)
        for doc in items:
            labels = (doc['tags'] or ['Ohne Tag']) if request.groups[depth] == 'tags' else [doc['correspondent']]
            for label in labels:
                buckets[label].append(doc)
        return [section for label in sorted(buckets, key=alphabetical)
                for section in group(buckets[label], depth + 1, (*path, label))]

    return {'title': request.title, 'start': request.start, 'end': request.end,
            'count': len(docs), 'sections': group(docs) if docs else [],
            'generated_at': datetime.now().astimezone().isoformat(),
            'groups': request.groups, 'sort': request.sort}


def render_pdf(index):
    font = 'Helvetica'
    font_path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if font_path.exists():
        if 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('DejaVu', str(font_path)))
        font = 'DejaVu'
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font
    styles.add(ParagraphStyle('Cell', fontName=font, fontSize=9, leading=13))
    styles.add(ParagraphStyle('Small', fontName=font, fontSize=8, leading=12, textColor=colors.HexColor('#596579')))
    output = BytesIO()
    pdf = SimpleDocTemplate(output, pagesize=(210*mm, 297*mm), rightMargin=18*mm,
                            leftMargin=18*mm, topMargin=18*mm, bottomMargin=20*mm,
                            title=index['title'], author='Paperless ASN Index')
    story = [Paragraph(escape(index['title']), styles['Title']),
             Paragraph(f"ASN {index['start']}–{index['end']} · {index['count']} Dokumente · "
                       f"Erstellt am {datetime.fromisoformat(index['generated_at']).strftime('%d.%m.%Y %H:%M')}", styles['Small']),
             Spacer(1, 8*mm)]
    if 'tags' in index['groups']:
        story.extend([Paragraph('Dokumente mit mehreren Tags werden unter jedem Tag aufgeführt.', styles['Small']), Spacer(1, 4*mm)])
    if not index['count']:
        story.append(Paragraph('Keine Dokumente mit ASN in diesem Bereich gefunden.', styles['Normal']))
    previous = []
    for section in index['sections']:
        for depth, label in enumerate(section['path']):
            if depth >= len(previous) or previous[:depth+1] != section['path'][:depth+1]:
                story.append(Paragraph(escape(label), styles['Heading2' if depth == 0 else 'Heading3']))
        previous = section['path']
        rows = [[Paragraph(label, styles['Cell']) for label in ['ASN', 'Dokument / Korrespondent', 'Datum']]]
        for doc in section['documents']:
            rows.append([Paragraph(str(doc['asn']), styles['Cell']),
                         Paragraph(escape(doc['title']) + '<br/><font size="8" color="#596579">' + escape(doc['correspondent']) + '</font>', styles['Cell']),
                         Paragraph('.'.join(reversed(doc['date'].split('-'))) if doc['date'] else '–', styles['Cell'])])
        table = Table(rows, colWidths=[20*mm, 126*mm, 28*mm], repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e9eef4')),
                                   ('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOTTOMPADDING',(0,0),(-1,-1),7),
                                   ('TOPPADDING',(0,0),(-1,-1),7),
                                   ('LINEBELOW',(0,0),(-1,-1),0.3,colors.HexColor('#d8e0e9'))]))
        story.extend([table, Spacer(1, 5*mm)])

    def footer(canvas, document):
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#596579'))
        canvas.drawString(18*mm, 12*mm, f"ASN {index['start']}–{index['end']}")
        canvas.drawRightString(192*mm, 12*mm, f'Seite {document.page}')
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
