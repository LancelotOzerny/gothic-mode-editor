"""Choices from installed/project scripts, without modifying game resources."""
import re

from .scripts import load_text, mask_comments, unquote


def item_options(repo, source):
    key = {'visual_effects': 'effect', 'item_schemes': 'scemename'}.get(source)
    if key is None:return []
    names = {unquote(item.fields[key]) for item in repo.game_items + repo.project_items if item.fields.get(key)}
    if source == 'visual_effects':
        roots = []
        if repo.game:roots.append(repo.game/'_work'/'Data'/'Scripts'/'System')
        if repo.root:roots.append(repo.root/'Scripts')
        for root in roots:
            if not root.is_dir():continue
            for path in root.rglob('*'):
                if path.suffix.lower() != '.d':continue
                try:code = mask_comments(load_text(path)[0])
                except OSError:continue
                names.update(re.findall(r'\bINSTANCE\s+([A-Za-z_]\w*)\s*\(\s*CFX_BASE\s*\)', code, re.I))
    return [(name, '"' + name + '"') for name in sorted(names, key=str.casefold) if name]
