"""Choices from installed/project scripts, without modifying game resources."""
import re

from .scripts import load_text, mask_comments, unquote
from .potion_schemes import POTION_SCHEMES
from .item_layout import project_scripts


def item_options(repo, source):
    if source == 'item_schemes':return list(POTION_SCHEMES)
    if source == 'item_actions':return action_catalog(repo).groups()
    if source == 'item_action_catalog':return action_catalog(repo)
    key = {'visual_effects': 'effect'}.get(source)
    if key is None:return []
    names = {unquote(item.fields[key]) for item in repo.game_items + repo.project_items if item.fields.get(key)}
    if source == 'visual_effects':
        cache=getattr(repo,'options_cache',{})
        cached=cache.get(source)
        if cached is not None:
            names.update(cached)
            return [(name,'"'+name+'"') for name in sorted(names,key=str.casefold) if name]
        discovered=set()
        roots = []
        if repo.game:roots.append(repo.game/'_work'/'Data'/'Scripts'/'System')
        if repo.root:roots.append(project_scripts(repo.root))
        for root in roots:
            if not root.is_dir():continue
            for path in root.rglob('*'):
                if path.suffix.lower() != '.d':continue
                try:code = mask_comments(load_text(path)[0])
                except OSError:continue
                discovered.update(re.findall(r'\bINSTANCE\s+([A-Za-z_]\w*)\s*\(\s*CFX_BASE\s*\)', code, re.I))
        cache[source]=discovered
        names.update(discovered)
    return [(name, '"' + name + '"') for name in sorted(names, key=str.casefold) if name]


def action_catalog(repo):
    from .item_actions import ActionCatalog
    cache=repo.options_cache
    if 'action_catalog' not in cache:cache['action_catalog']=ActionCatalog(repo.root,repo._game_content())
    return cache['action_catalog']
