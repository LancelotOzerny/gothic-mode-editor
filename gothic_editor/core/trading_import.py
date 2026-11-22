"""Read item rows from vanilla merchant functions, not NPC instances."""
import re
from pathlib import Path

from .daedalus_merge import ScriptTree
from .scripts import mask_comments

ITEMS = re.compile(r'\bCreateInvItems\s*\(\s*\w+\s*,\s*([A-Za-z_]\w*)\s*,\s*(\d+)\s*\)', re.I)
CHAPTER = re.compile(r'\bKapitel\s*>=\s*([1-6])\b', re.I)

def game_trade_goods(content):
    """Return item rows annotated with their source trading function."""
    root = Path(content)
    if not root.is_dir():
        raise ValueError('Не найдены скрипты Gothic для импорта товаров.')
    tree = ScriptTree(root)
    result = []
    for key, matches in tree.symbols.items():
        if not key.startswith('b_givetradeinv_') or len(matches) != 1:
            continue
        path, definition = matches[0]
        if definition.kind != 'func':
            continue
        block = mask_comments(tree.documents[path].text[definition.start:definition.end])
        chapter = 1
        for line in block.splitlines():
            found = CHAPTER.search(line)
            if found:
                chapter = int(found[1])
            for match in ITEMS.finditer(line):
                result.append({'source': definition.names[0], 'item': match[1],
                               'quantity': int(match[2]), 'chapter': chapter})
    return result
