"""Compile small Markdown-like Gothic books and notes without touching source files.

Gothic's ordinary document UI has one/two visible pages; enforce that limit
instead of silently generating unreachable content.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from .daedalus_merge import definitions

DOCUMENT_ROOT = Path('Assets/Texts/Documents')
MAX_PAGES = 2
# Conservative preview budgets; Gothic fonts vary with language / font assets.
MAX_LINES = 13
LINE_WIDTH = 37
HEADING_WIDTH = 23


def document_files(project):
    root = (Path(project) / DOCUMENT_ROOT).resolve()
    base = Path(project).resolve()
    if not root.is_relative_to(base) or not root.is_dir():
        return ()
    result = []
    for file in sorted(root.rglob('*')):
        if file.is_file() and file.suffix.casefold() in ('.md', '.txt'):
            if not file.resolve().is_relative_to(root):
                continue
            result.append(file.relative_to(base).as_posix())
    return tuple(result)


def load_document(project, reference):
    if not isinstance(reference, str) or not reference or '\\' in reference:
        raise ValueError('Выберите текст книги или записки в Assets/Texts/Documents.')
    project = Path(project).resolve()
    root = (project / DOCUMENT_ROOT).resolve()
    path = (project / reference).resolve()
    if (not path.is_relative_to(root) or path.suffix.casefold() not in ('.md', '.txt')
            or not path.is_file()):
        raise ValueError('Недоступный файл текста документа: ' + str(reference))
    if path.stat().st_size > 128 * 1024:
        raise ValueError('Текст документа превышает 128 КБ.')
    raw = path.read_text('utf-8-sig')
    raw.encode('cp1251')
    return raw


def parsed_blocks(raw):
    """Paragraphs and # headings; other Markdown constructs are plain text."""
    blocks = []
    paragraph = []
    def flush():
        if paragraph:
            blocks.append(('text', ' '.join(paragraph)))
            paragraph.clear()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            flush()
        elif line.startswith('# '):
            flush()
            title = line[2:].strip()
            if title:
                blocks.append(('heading', title))
        else:
            paragraph.append(line)
    flush()
    if not blocks:
        raise ValueError('Документ пуст. Добавьте заголовок или текст.')
    return blocks


def paginate(raw):
    pages = [[]]
    used = 0
    for kind, value in parsed_blocks(raw):
        width = HEADING_WIDTH if kind == 'heading' else LINE_WIDTH
        # Gothic fonts are proportional. This is intentionally conservative,
        # not a pixel-perfect measurement.
        lines = textwrap.wrap(value, width=width,
                              break_long_words=False,
                              break_on_hyphens=False) or ['']
        while lines:
            if pages[-1]:
                if used + 1 >= MAX_LINES:
                    pages.append([])
                    used = 0
                else:
                    used += 1  # One paragraph gap
            available = MAX_LINES - used
            if kind == 'heading' and len(lines) > available and pages[-1]:
                pages.append([])
                used = 0
                available = MAX_LINES
            if len(pages) > MAX_PAGES:
                raise ValueError('Текст занимает более двух страниц Gothic. Сократите или разделите книгу.')
            chunk, lines = lines[:available], lines[available:]
            # The engine wraps each paragraph again to the actual font width.
            pages[-1].append((kind, ' '.join(chunk)))
            used += len(chunk)
            if lines:
                pages.append([])
                used = 0
    if len(pages) > MAX_PAGES:
        raise ValueError('Текст занимает более двух страниц Gothic. Сократите или разделите книгу.')
    return pages

def literal(text):
    if '\x00' in text or any(ord(c) < 32 for c in text):
        raise ValueError('Недопустимые управляющие символы в тексте книги.')
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def render_document(instance, raw, *, book=False):
    pages = paginate(raw)
    lines = [f'func void GE_ShowDocument_{instance}()',
             '{', '    var int doc;', '    doc = Doc_Create();',
             f'    Doc_SetPages(doc, {len(pages)});']
    textures = ('Book_Mage_L.tga', 'Book_Mage_R.tga') if book else ('letters.TGA', 'letters.TGA')
    for page, blocks in enumerate(pages):
        lines.extend((f'    Doc_SetPage(doc, {page}, {literal(textures[page])}, FALSE);',
                      f'    Doc_SetMargins(doc, {page}, 60, 40, 60, 40, TRUE);'))
        for number, (kind, value) in enumerate(blocks):
            if number:
                lines.append(f'    Doc_PrintLine(doc, {page}, "");')
            font = 'FONT_BookHeadline' if kind == 'heading' else 'FONT_Book'
            lines.append(f'    Doc_SetFont(doc, {page}, {font});')
            # Chunks are bounded to keep compiler string literals manageable.
            for chunk in textwrap.wrap(value, width=180,
                                       break_long_words=False, break_on_hyphens=False):
                lines.append(f'    Doc_PrintLines(doc, {page}, {literal(chunk)});')
    lines.extend(('    Doc_Show(doc);', '};'))
    script = '\n'.join(lines)
    definitions(script, instance)
    return script
