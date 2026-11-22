"""Compile small Markdown-like Gothic books and notes without touching source files.

Vanilla Gothic shows only one spread. Reopening a long book displays the next spread.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from .daedalus_merge import definitions

DOCUMENT_ROOT = Path('Assets/Texts')
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
        raise ValueError('Выберите текст книги или записки в Assets/Texts.')
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


def paginate(raw, *, book=False):
    pages = [[]]
    used = 0
    max_lines = 10 if book else MAX_LINES
    for kind, value in parsed_blocks(raw):
        width = (19 if kind == 'heading' else 24) if book else (HEADING_WIDTH if kind == 'heading' else LINE_WIDTH)
        # Gothic fonts are proportional. This is intentionally conservative,
        # not a pixel-perfect measurement.
        lines = textwrap.wrap(value, width=width,
                              break_long_words=False,
                              break_on_hyphens=False) or ['']
        while lines:
            if pages[-1]:
                if used + 1 >= max_lines:
                    pages.append([])
                    used = 0
                else:
                    used += 1  # One paragraph gap
            available = max_lines - used
            if kind == 'heading' and len(lines) > available and pages[-1]:
                pages.append([])
                used = 0
                available = max_lines
            chunk, lines = lines[:available], lines[available:]
            # The engine wraps each paragraph again to the actual font width.
            pages[-1].append((kind, ' '.join(chunk)))
            used += len(chunk)
            if lines:
                pages.append([])
                used = 0
    return pages

def literal(text):
    if '\x00' in text or any(ord(c) < 32 for c in text):
        raise ValueError('Недопустимые управляющие символы в тексте книги.')
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _render_spread(function_name, pages, *, book=False):
    """Create a normal Gothic document displaying one or two pages."""
    lines = [f'func void {function_name}()',
             '{', '    var int doc;', '    doc = Doc_Create();',
             f'    Doc_SetPages(doc, {len(pages)});']
    textures = ('Book_Mage_L.tga', 'Book_Mage_R.tga') if book else ('letters.TGA', 'letters.TGA')
    for page, blocks in enumerate(pages):
        margins = ((275, 20, 30, 20) if page == 0 else (30, 20, 275, 20)) if book else (50, 50, 50, 50)
        lines.extend((f'    Doc_SetPage(doc, {page}, {literal(textures[page])}, FALSE);',
                      f'    Doc_SetMargins(doc, {page}, {margins[0]}, {margins[1]}, {margins[2]}, {margins[3]}, TRUE);'))
        for number, (kind, value) in enumerate(blocks):
            if number:
                lines.append(f'    Doc_PrintLine(doc, {page}, "");')
            font = 'FONT_BookHeadline' if kind == 'heading' else 'FONT_Book'
            lines.append(f'    Doc_SetFont(doc, {page}, {font});')
            for chunk in textwrap.wrap(value, width=180,
                                       break_long_words=False, break_on_hyphens=False):
                lines.append(f'    Doc_PrintLines(doc, {page}, {literal(chunk)});')
    lines.extend(('    Doc_Show(doc);', '};'))
    return '\n'.join(lines)


def render_document(instance, raw, *, book=False):
    pages = paginate(raw, book=book)
    name = f'GE_ShowDocument_{instance}'
    if len(pages) <= 2:
        script = _render_spread(name, pages, book=book)
    else:
        # Vanilla Gothic cannot turn a page in an open document.
        # Reusing the item shows successive spreads (including after saving).
        spreads = [pages[index:index + 2] for index in range(0, len(pages), 2)]
        state = f'GE_DocSpread_{instance}'
        parts = [f'var int {state};']
        for index, spread in enumerate(spreads):
            parts.append(_render_spread(f'{name}_Part_{index}', spread, book=book))
        lines = [f'func void {name}()', '{']
        lines.extend((
            f'    if ({state} < 0) {{ {state} = 0; }};',
            f'    if ({state} >= {len(spreads)}) {{ {state} = 0; }};',
        ))
        for index in range(len(spreads)):
            lines.append(f'    if ({state} == {index}) {{ {name}_Part_{index}(); }};')
        lines.extend((
            f'    {state} = {state} + 1;',
            f'    if ({state} >= {len(spreads)}) {{ {state} = 0; }};',
            '};',
        ))
        parts.append('\n'.join(lines))
        script = '\n\n'.join(parts)
    definitions(script, instance)
    return script
