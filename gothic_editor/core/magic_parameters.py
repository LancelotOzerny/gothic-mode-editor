"""Read and override spell mana constants without altering installed Gothic scripts."""
from pathlib import Path
import re

from .categories import classify
from .item_layout import project_scripts
from .scripts import load_text, mask_comments, parse_items, with_item_metadata

_COST = re.compile(r'\bconst\s+int\s+(SPL_Cost_[A-Za-z_]\w*)\s*=\s*([^;]+);', re.I)
_IDENTIFIER = re.compile(r'[A-Za-z_]\w*', re.ASCII)
_INTEGER = re.compile(r'\d+', re.ASCII)


def _constants(folder):
    """Collect uniquely defined integer costs from scripts under folder."""
    result = {}
    if folder is None or not folder.is_dir():
        return result
    for path in sorted(folder.rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.d':
            continue
        try:
            source, _ = load_text(path)
        except (OSError, UnicodeError):
            continue
        for match in _COST.finditer(mask_comments(source)):
            key = match.group(1).casefold()
            value = match.group(2).strip()
            if key in result and result[key] != (match.group(1), value):
                result[key] = None
            elif key not in result:
                result[key] = (match.group(1), value)
    return {key: value for key, value in result.items() if value is not None}


def discover_mana_cost(repo, item):
    """Find a literal mana cost for a rune or scroll; return None if uncertain."""
    category = classify(item)
    if category not in ('runes', 'scrolls'):
        return None
    spell = item.fields.get('spell', '').strip()
    if not _IDENTIFIER.fullmatch(spell) or not spell.lower().startswith('spl_'):
        return None
    catalog = repo.options_cache.get('magic_cost_constants')
    if catalog is None:
        catalog = _constants(repo._game_content())
        repo.options_cache['magic_cost_constants'] = catalog
    # Gothic II scrolls use a shared scroll cost in Spell_ProcessMana;
    # runes generally use SPL_Cost_<spell suffix>.
    candidate = 'SPL_Cost_Scroll' if category == 'scrolls' else 'SPL_Cost_' + spell[4:]
    found = catalog.get(candidate.casefold())
    if found is None or not _INTEGER.fullmatch(found[1]):
        return None
    return {'magic_cost_symbol': found[0], 'magic_cost': found[1],
            'magic_cost_original': found[1]}


def import_mana_metadata(repo, item):
    """Insert editor-only cost metadata into an imported INSTANCE."""
    metadata = discover_mana_cost(repo, item)
    if metadata is None:
        return item.text
    return with_item_metadata(item.text, {**item.editor_metadata, **metadata})


def apply_magic_costs(project, content):
    """Modify only staging copies of cost declarations, never game files.

    Different item overrides of one shared spell/scroll constant must agree.
    An unknown or ambiguous symbol is an error, not a silent no-op.
    """
    source = project_scripts(project) / 'Content'
    if not source.is_dir():
        return []
    requests = {}
    for path in sorted(source.rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.d':
            continue
        for item in parse_items(path, 'project'):
            metadata = item.editor_metadata
            symbol = metadata.get('magic_cost_symbol', '')
            value = metadata.get('magic_cost', '')
            if not symbol:
                if value:
                    raise ValueError(f'{item.instance}: укажите константу расхода маны SPL_Cost_*')
                continue
            if not _IDENTIFIER.fullmatch(symbol) or not symbol.lower().startswith('spl_cost_'):
                raise ValueError(f'{item.instance}: некорректная константа стоимости маны')
            if not _INTEGER.fullmatch(value) or int(value) > 2147483647:
                raise ValueError(f'{item.instance}: расход маны должен быть целым числом от 0 до 2147483647')
            # Imported values are only snapshots. Apply an override only if
            # it was actually edited. In particular, all scrolls share one
            # SPL_Cost_Scroll constant in stock Gothic.
            if metadata.get('magic_cost_original') == value:
                continue
            key = symbol.casefold()
            if key in requests and requests[key] != value:
                raise ValueError(f'Разный расход маны для общей константы {symbol}. '
                                 'Установите одинаковое значение у связанных предметов.')
            requests[key] = value
    if not requests:
        return []
    occurrences = {}
    for path in sorted(content.rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.d':
            continue
        source_text, codec = load_text(path)
        for match in _COST.finditer(mask_comments(source_text)):
            key = match.group(1).casefold()
            if key in requests:
                occurrences.setdefault(key, []).append((path, source_text, codec, match.start(2), match.end(2)))
    for key in requests:
        if len(occurrences.get(key, ())) != 1:
            raise ValueError(f'Невозможно однозначно изменить стоимость маны {key}: '
                             'константа не найдена или определена несколько раз.')
    changes = {}
    for key, value in requests.items():
        path, source_text, codec, start, end = occurrences[key][0]
        changes.setdefault(path, []).append((start, end, value))
    for path, replacements in changes.items():
        source_text, codec = load_text(path)
        for start, end, value in sorted(replacements, reverse=True):
            source_text = source_text[:start] + value + source_text[end:]
        path.write_bytes(source_text.encode(codec))
    return list(changes)
