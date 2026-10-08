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
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, PageBreak, Paragraph, Spacer, Table, TableStyle


class LocationRule(BaseModel):
    start: int = Field(ge=0, le=2147483647)
    end: int = Field(ge=0, le=2147483647)
    label: str = Field(min_length=1, max_length=150)


class IndexRequest(BaseModel):
    start: int = Field(ge=0, le=2147483647)
    end: int = Field(ge=0, le=2147483647)
    groups: list[Literal['tags', 'correspondent', 'year', 'document_type']] = Field(default_factory=list, max_length=4)
    sort: Literal['title', 'asn', 'date', 'date_desc'] = 'title'
    title: str = Field(default='Archivverzeichnis', min_length=1, max_length=150)
    selected_tags: list[int] | None = Field(default=None, max_length=1000)
    tag_mode: Literal['multiple', 'priority'] = 'multiple'
    tag_priority: list[int] = Field(default_factory=list, max_length=1000)
    year_desc: bool = False
    location_field: int | None = Field(default=None, ge=1)
    location_rules: list[LocationRule] = Field(default_factory=list, max_length=100)
    correspondent_register: bool = True
    show_gaps: bool = False
    pdf_toc: bool = True
    new_group_page: bool = False

    @model_validator(mode='after')
    def validate_range(self):
        if self.end < self.start:
            raise ValueError('Die ASN bis muss mindestens so groß wie die ASN von sein.')
        if len(set(self.groups)) != len(self.groups):
            raise ValueError('Eine Gruppierung darf nur einmal vorkommen.')
        for values in (self.selected_tags, self.tag_priority):
            if values is not None and len(set(values)) != len(values):
                raise ValueError('Tag-Auswahl und Priorität dürfen keine doppelten IDs enthalten.')
        ordered = sorted(self.location_rules, key=lambda r: r.start)
        for i, rule in enumerate(ordered):
            if rule.end < rule.start or not rule.label.strip():
                raise ValueError('Ablageorte benötigen einen gültigen ASN-Bereich und eine Bezeichnung.')
            if i and rule.start <= ordered[i-1].end:
                raise ValueError('ASN-Bereiche der Ablageorte dürfen sich nicht überschneiden.')
        return self


def alphabetical(value):
    value = str(value).casefold().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
    return ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))


def missing_ranges(start, end, present):
    """Compress gaps without iterating over potentially billions of ASN values."""
    result, cursor = [], start
    for value in sorted(set(present)):
        if value > cursor:
            result.append({'start': cursor, 'end': value - 1})
        cursor = value + 1
    if cursor <= end:
        result.append({'start': cursor, 'end': end})
    return result


def build_index(documents, tags, correspondents, request, document_types=None, custom_fields=None):
    tag_names = {t['id']: t['name'] for t in tags}
    correspondent_names = {c['id']: c['name'] for c in correspondents}
    type_names = {t['id']: t['name'] for t in document_types or []}
    field = next((f for f in custom_fields or [] if f['id'] == request.location_field), None)
    selection = set(request.selected_tags) if request.selected_tags is not None else None
    priority = {tag: i for i, tag in enumerate(request.tag_priority)}
    docs, seen = [], set()
    for doc in documents:
        asn = doc.get('archive_serial_number')
        if asn is None or not request.start <= asn <= request.end or doc['id'] in seen:
            continue
        seen.add(doc['id'])
        all_tags = list(dict.fromkeys(doc.get('tags', [])))
        group_tags = [t for t in all_tags if selection is None or t in selection]
        group_tags.sort(key=lambda t: (priority.get(t, len(priority)), alphabetical(tag_names.get(t, f'Tag #{t}')), t))
        if request.tag_mode == 'priority':
            group_tags = group_tags[:1]
        location = ''
        if request.location_field:
            value = next((f.get('value') for f in doc.get('custom_fields', []) if f['field'] == request.location_field), None)
            if value is not None:
                if field and field.get('data_type') == 'select':
                    options = (field.get('extra_data') or {}).get('select_options', [])
                    value = next((o['label'] for o in options if str(o['id']) == str(value)), value)
                location = str(value).strip()
        if not location:
            location = next((r.label for r in request.location_rules if r.start <= asn <= r.end), '')
        date = (doc.get('created') or '')[:10]
        docs.append({
            'id': doc['id'], 'asn': asn, 'title': doc.get('title') or 'Ohne Titel', 'date': date,
            'year': date[:4] if date else 'Ohne Jahr',
            'tags': sorted({tag_names.get(t, f'Tag #{t}') for t in all_tags}, key=alphabetical),
            'group_tags': [tag_names.get(t, f'Tag #{t}') for t in group_tags],
            'correspondent': correspondent_names.get(doc.get('correspondent'), 'Ohne Korrespondent'),
            'document_type': type_names.get(doc.get('document_type'), 'Ohne Dokumenttyp'),
            'location': location,
        })
    key = {'title': lambda d: (alphabetical(d['title']), d['asn']),
           'asn': lambda d: (d['asn'], alphabetical(d['title'])),
           'date': lambda d: (d['date'], d['asn']),
           'date_desc': lambda d: (d['date'], -d['asn'])}[request.sort]

    def group(items, depth=0, path=()):
        if depth == len(request.groups):
            return [{'path': list(path), 'documents': sorted(items, key=key, reverse=request.sort == 'date_desc')}]
        kind = request.groups[depth]
        buckets = defaultdict(list)
        for doc in items:
            labels = (doc['group_tags'] or ['Ohne passenden Tag' if selection is not None else 'Ohne Tag']) if kind == 'tags' else [doc[kind]]
            for label in labels:
                buckets[label].append(doc)
        labels = sorted(buckets, key=alphabetical)
        if kind == 'year' and request.year_desc:
            labels = sorted((v for v in labels if v != 'Ohne Jahr'), reverse=True) + (['Ohne Jahr'] if 'Ohne Jahr' in labels else [])
        return [section for label in labels for section in group(buckets[label], depth + 1, (*path, label))]

    register = defaultdict(set)
    for doc in docs:
        register[doc['correspondent']].add(doc['asn'])
    gaps = missing_ranges(request.start, request.end, [d['asn'] for d in docs]) if request.show_gaps else []
    return {'title': request.title, 'start': request.start, 'end': request.end,
            'count': len(docs), 'sections': group(docs) if docs else [],
            'generated_at': datetime.now().astimezone().isoformat(),
            'groups': request.groups, 'sort': request.sort, 'config': request.model_dump(),
            'register': [{'name': name, 'asns': sorted(register[name])} for name in sorted(register, key=alphabetical)] if request.correspondent_register else [],
            'gaps': gaps, 'gap_count': sum(r['end'] - r['start'] + 1 for r in gaps)}


class IndexPDF(BaseDocTemplate):
    def beforeDocument(self):
        self.heading_number = 0
        self.current_group = ''

    def afterFlowable(self, flowable):
        if not hasattr(flowable, 'outline_level'):
            return
        level = flowable.outline_level
        text = flowable.getPlainText()
        bookmark = f'heading-{self.heading_number}'
        self.heading_number += 1
        self.canv.bookmarkPage(bookmark)
        self.canv.addOutlineEntry(text, bookmark, level=level, closed=False)
        self.notify('TOCEntry', (level, escape(text), self.page, bookmark))
        self.current_group = flowable.group_path


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
    pdf = IndexPDF(output, pagesize=(210*mm, 297*mm), rightMargin=18*mm,
                            leftMargin=18*mm, topMargin=24*mm, bottomMargin=20*mm,
                            title=index['title'], author='Paperless ASN Index')
    story = [Paragraph(escape(index['title']), styles['Title']),
             Paragraph(f"ASN {index['start']}–{index['end']} · {index['count']} Dokumente · "
                       f"Erstellt am {datetime.fromisoformat(index['generated_at']).strftime('%d.%m.%Y %H:%M')}", styles['Small']),
             Spacer(1, 8*mm)]
    config = index.get('config', {})
    if 'tags' in index['groups']:
        note = 'Dokumente werden einmal nach Tag-Priorität zugeordnet.' if config.get('tag_mode') == 'priority' else 'Dokumente werden unter jedem passenden Gruppierungs-Tag aufgeführt.'
        story.extend([Paragraph(note, styles['Small']), Spacer(1, 4*mm)])
    if config.get('pdf_toc') and (index['groups'] and index['sections'] or index.get('register') or config.get('show_gaps')):
        story.append(Paragraph('Inhaltsverzeichnis', styles['Heading2']))
        toc = TableOfContents()
        toc.levelStyles = [ParagraphStyle(f'TOC{i}', fontName=font, fontSize=10 if i == 0 else 9,
                                         leading=15, leftIndent=i*12, firstLineIndent=0, spaceBefore=4)
                           for i in range(4)]
        story.extend([toc, PageBreak()])

    def heading(label, depth=0, path=None):
        item = Paragraph(escape(label), styles['Heading2' if depth == 0 else 'Heading3'])
        item.outline_level = depth
        item.group_path = ' / '.join(path or [label])
        return item
    if not index['count']:
        story.append(Paragraph('Keine Dokumente mit ASN in diesem Bereich gefunden.', styles['Normal']))
    previous = []
    for section in index['sections']:
        if config.get('new_group_page') and previous and section['path'] and previous[0] != section['path'][0]:
            story.append(PageBreak())
        for depth, label in enumerate(section['path']):
            if depth >= len(previous) or previous[:depth+1] != section['path'][:depth+1]:
                story.append(heading(label, depth, section['path'][:depth+1]))
        previous = section['path']
        rows = [[Paragraph(label, styles['Cell']) for label in ['ASN', 'Dokument / Korrespondent', 'Datum']]]
        for doc in section['documents']:
            rows.append([Paragraph(str(doc['asn']), styles['Cell']),
                         Paragraph(escape(doc['title']) + '<br/><font size="8" color="#596579">' + escape(doc['correspondent']) + '<br/>' + escape(doc['document_type']) + (' · ' + escape(', '.join(doc['tags'])) if doc['tags'] else '') + ('<br/>Ablage: ' + escape(doc['location']) if doc['location'] else '') + '</font>', styles['Cell']),
                         Paragraph('.'.join(reversed(doc['date'].split('-'))) if doc['date'] else '–', styles['Cell'])])
        table = Table(rows, colWidths=[20*mm, 126*mm, 28*mm], repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e9eef4')),
                                   ('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOTTOMPADDING',(0,0),(-1,-1),7),
                                   ('TOPPADDING',(0,0),(-1,-1),7),
                                   ('LINEBELOW',(0,0),(-1,-1),0.3,colors.HexColor('#d8e0e9'))]))
        story.extend([table, Spacer(1, 5*mm)])

    if index.get('register'):
        story.extend([PageBreak(), heading('Korrespondentenregister')])
        for entry in index['register']:
            story.extend([Paragraph(escape(entry['name']), styles['Heading3']),
                          Paragraph('ASN ' + ', '.join(map(str, entry['asns'])), styles['Cell']), Spacer(1, 3*mm)])
    if config.get('show_gaps'):
        story.extend([PageBreak(), heading('ASN-Abgleich'),
                      Paragraph('Nicht im API-Ergebnis vorhanden. Nummern können unbenutzt sein oder dem API-Benutzer fehlen.', styles['Small']),
                      Spacer(1, 4*mm), Paragraph(f"{index['gap_count']} ASN nicht im API-Ergebnis vorhanden.", styles['Normal'])])
        for gap in index['gaps']:
            label = str(gap['start']) if gap['start'] == gap['end'] else f"{gap['start']}–{gap['end']}"
            story.append(Paragraph(label, styles['Cell']))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#596579'))
        group = document.current_group
        while pdfmetrics.stringWidth(group, font, 8) > 174*mm:
            group = group[:-4] + '…'
        canvas.drawString(18*mm, 283*mm, group)
        canvas.drawString(18*mm, 12*mm, f"ASN {index['start']}–{index['end']}")
        canvas.drawRightString(192*mm, 12*mm, f'Seite {document.page}')
        canvas.restoreState()
    frame = Frame(pdf.leftMargin, pdf.bottomMargin, pdf.width, pdf.height, id='body', leftPadding=0, rightPadding=0)
    pdf.addPageTemplates(PageTemplate(id='index', frames=[frame], onPageEnd=footer))
    pdf.multiBuild(story)
    return output.getvalue()
