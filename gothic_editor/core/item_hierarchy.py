"""Project-only hierarchy. Category codes never replace script/schema identifiers."""
from copy import deepcopy
from dataclasses import dataclass
import json
import re
from pathlib import Path
from uuid import uuid4

from .asset_files import AssetFiles
from .categories import CATEGORIES, Category, classify, get_category, walk_categories
from .localization import tr


@dataclass
class HierarchyNode(Category):
    kind: str = 'category'
    source: str = ''
    code: str = ''
    parent: str = ''


class ItemHierarchy:
    def __init__(self, project):
        self.files = AssetFiles(project)
        self.path = self.files.checked(Path(project) / 'Assets/Items/hierarchy.json')
        self.reload()

    @staticmethod
    def defaults():
        rows = []
        def append(categories, parent=''):
            for category in categories:
                rows.append(dict(key=category.key, parent=parent, kind='category',
                                 source=category.key, code=category.key, name=''))
                append(category.children, category.key)
        append(CATEGORIES)
        return dict(schema_version=1, nodes=rows, items={})

    def reload(self):
        self.files.checked(self.path)
        data = json.loads(self.path.read_text('utf-8')) if self.path.exists() else self.defaults()
        self.validate(data)
        self.data = data

    @staticmethod
    def validate(data):
        error = 'Некорректный файл иерархии предметов.'
        if (not isinstance(data, dict) or data.get('schema_version') != 1 or
                not isinstance(data.get('nodes'), list) or not isinstance(data.get('items'), dict)):
            raise ValueError(error)
        sources = {node.key for node in walk_categories()}
        rows, codes = {}, set()
        for row in data['nodes']:
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str)
                    for key in ('key', 'parent', 'kind', 'source', 'name')):
                raise ValueError(error)
            if (not row['key'] or row['key'] in rows or row['source'] not in sources or
                    row['kind'] not in ('category', 'group') or any(c in row['name'] for c in '\r\n\0')):
                raise ValueError(error)
            if row['kind'] == 'category':
                code = row.get('code')
                if (not isinstance(code, str) or not re.fullmatch(r'[A-Za-z_]\w*', code, re.ASCII)
                        or code.casefold() in codes):
                    raise ValueError('Код категории некорректен или уже занят.')
            elif not row['parent'] or not row['name'].strip() or 'code' in row:
                raise ValueError(error)
            code = row.get('code', '')
            if not isinstance(code, str) or (code and not re.fullmatch(r'[A-Za-z_]\w*', code, re.ASCII)):
                raise ValueError(error)
            if code and code.casefold() in codes:
                raise ValueError('Код категории или группы уже занят.')
            if code:codes.add(code.casefold())
            rows[row['key']] = row
        for key, row in rows.items():
            seen = {key}
            parent = row['parent']
            while parent:
                if parent not in rows or parent in seen:raise ValueError(error)
                seen.add(parent)
                parent = rows[parent]['parent']
            if row['parent']:
                parent = rows[row['parent']]
                allowed = {node.key for node in walk_categories([get_category(parent['source'])])}
                if row['source'] not in allowed:raise ValueError(error)
        for instance, target in data['items'].items():
            if (not isinstance(instance, str) or not re.fullmatch(r'[a-z_]\w*', instance, re.ASCII)
                    or not isinstance(target, str) or target not in rows):
                raise ValueError(error)

    def commit(self, data):
        self.validate(data)
        self.files.checked(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.files.checked(self.path.with_name('.hierarchy-' + uuid4().hex + '.tmp'))
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', 'utf-8')
            temporary.replace(self.path)
        finally:temporary.unlink(missing_ok=True)
        self.data = data

    def row(self, key):
        return next(row for row in self.data['nodes'] if row['key'] == key)

    @staticmethod
    def title(row):
        return row['name'] or tr('categories.' + row['source'])

    def tree(self):
        nodes = {row['key']: HierarchyNode(self.title(row), get_category(row['source']).icon,
                    row['key'], kind=row['kind'], source=row['source'],
                    code=row.get('code', ''), parent=row['parent']) for row in self.data['nodes']}
        roots = []
        for node in nodes.values():
            if node.parent:nodes[node.parent].children.append(node)
            else:roots.append(node)
        return roots

    def accepts(self, key, item):
        return classify(item) in {node.key for node in walk_categories([get_category(self.row(key)['source'])])}

    def location(self, item):
        key = self.data['items'].get(item.instance.casefold())
        if key and self.accepts(key, item):return key
        category = classify(item)
        # Prefer the original category, then a surviving duplicate, then its ancestor.
        rows = [row for row in self.data['nodes'] if row['kind'] == 'category']
        for row in rows:
            if row['key'] == category:return row['key']
        for row in rows:
            if row['source'] == category:return row['key']
        for row in reversed(rows):
            if self.accepts(row['key'], item):return row['key']
        return ''  # Removing the last category never hides or deletes its items.

    def create_group(self, parent):
        row = self.row(parent)
        key = uuid4().hex
        data = deepcopy(self.data)
        data['nodes'].append(dict(key=key, parent=parent, kind='group', source=row['source'],
                                  name='Новая группа'))
        self.commit(data)
        return key

    def rename(self, key, name, code=None):
        name = name.strip()
        if not name:raise ValueError('Название не должно быть пустым.')
        data = deepcopy(self.data)
        row = next(row for row in data['nodes'] if row['key'] == key)
        row['name'] = name
        if row['kind'] == 'category':
            row['code'] = (code if code is not None else row['code']).strip()
        self.commit(data)

    def descendants(self, key):
        keys = {key}
        pending = [key]
        while pending:
            parent = pending.pop()
            for row in self.data['nodes']:
                if row['parent'] == parent:
                    keys.add(row['key'])
                    pending.append(row['key'])
        return keys

    def duplicate(self, key):
        """Copy the visual subtree; return old/new keys for copying item definitions."""
        keys = self.descendants(key)
        mapping = {old: uuid4().hex for old in keys}
        data = deepcopy(self.data)
        codes = {row.get('code', '').casefold() for row in data['nodes']}
        for original in self.data['nodes']:
            if original['key'] not in keys:continue
            row = deepcopy(original)
            row['key'] = mapping[original['key']]
            row['parent'] = mapping.get(original['parent'], original['parent'])
            if original['key'] == key:row['name'] = self.title(original) + ' (копия)'
            if row.get('code'):
                base = row['code'] + '_Copy'
                code, number = base, 2
                while code.casefold() in codes:
                    code = f'{base}_{number}'
                    number += 1
                row['code'] = code
                codes.add(code.casefold())
            data['nodes'].append(row)
        self.commit(data)
        return mapping

    def delete(self, key):
        parent = self.row(key)['parent']
        keys = self.descendants(key)
        data = deepcopy(self.data)
        data['nodes'] = [row for row in data['nodes'] if row['key'] not in keys]
        for instance, target in list(data['items'].items()):
            if target not in keys:continue
            if parent:data['items'][instance] = parent
            else:del data['items'][instance]
        self.commit(data)

    def assign(self, item, key):
        self.assign_many([item], key)

    def assign_many(self, items, key):
        items = list(items)
        if key and any(not self.accepts(key, item) for item in items):
            raise ValueError('Предмет и группа должны принадлежать одной категории.')
        data = deepcopy(self.data)
        for item in items:
            if key:data['items'][item.instance.casefold()] = key
            else:data['items'].pop(item.instance.casefold(), None)
        self.commit(data)

    def move_data(self, values, key):
        """Validate a complete drop before writing; keep selected subtrees intact."""
        rows = {row['key']:row for row in self.data['nodes']}
        if key and key not in rows:raise ValueError('Цель переноса не найдена.')
        groups = {value.key for value in values if isinstance(value, HierarchyNode)}
        covered = set()
        for group in groups:
            if group not in rows or rows[group]['kind'] != 'group':
                raise ValueError('Переносить можно группы и предметы, но не категории.')
            subtree = self.descendants(group)
            if key in subtree:raise ValueError('Нельзя перенести группу в себя или в её потомка.')
            covered.update(subtree)
        roots = [group for group in groups if not any(group in self.descendants(other)
                 for other in groups if other != group)]
        data = deepcopy(self.data)
        for group in roots:
            source = rows[group]['source']
            target = key or next((row['key'] for row in self.data['nodes']
                                  if row['kind']=='category' and row['source']==source), None)
            if not target:raise ValueError('Исходная категория группы удалена.')
            allowed = {node.key for node in walk_categories([get_category(rows[target]['source'])])}
            if source not in allowed:raise ValueError('Группы должны принадлежать совместимым категориям.')
            next(row for row in data['nodes'] if row['key']==group)['parent'] = target
        for value in values:
            if isinstance(value, HierarchyNode):continue
            if key and not self.accepts(key,value):
                raise ValueError('Предмет и группа должны принадлежать одной категории.')
            if self.location(value) in covered:continue
            if key:data['items'][value.instance.casefold()] = key
            else:data['items'].pop(value.instance.casefold(),None)
        self.validate(data)
        return data

    def can_move(self, values, key):
        try:self.move_data(values,key)
        except ValueError:return False
        return True

    def move_many(self, values, key):
        self.commit(self.move_data(values,key))

    def transfer(self, previous, updated=None, copy=False):
        """Keep membership on item ID changes, copies and deletion."""
        old = previous.instance.casefold()
        if old not in self.data['items']:return
        data = deepcopy(self.data)
        target = data['items'][old]
        if not copy:del data['items'][old]
        if updated is not None:data['items'][updated.instance.casefold()] = target
        if data != self.data:self.commit(data)
