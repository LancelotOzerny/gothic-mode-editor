"""Project alchemy menu categories and stock Gothic bindings."""
import json
from pathlib import Path
from copy import deepcopy
from .recipes import identifier, RecipeError
from .asset_files import AssetFiles

STOCK = {'health': 'Health', 'mana': 'Mana', 'special': 'Special', 'booze': 'Booze', 'tabak': 'Tabak'}
DEFAULTS = [{'id': key, 'name': name} for key, name in zip(STOCK,
    ('Зелья здоровья', 'Зелья маны', 'Особые зелья', 'Алкоголь', 'Табак'))]


def stock_binding(row):
    return row.get('binding', row['id'] if row['id'] in STOCK else None)


class RecipeCategories:
    def __init__(self, project):
        self.files = AssetFiles(project)
        self.path = self.files.checked(Path(project)/'Assets/Recipes/categories.json')

    def load(self):
        self.files.checked(self.path)
        if not self.path.exists():return deepcopy(DEFAULTS)
        data = json.loads(self.path.read_text('utf-8'))
        if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('categories'), list):
            raise RecipeError('category', 'Некорректный файл категорий рецептов.')
        rows, seen, bindings = data['categories'], set(), set()
        for row in rows:
            if not isinstance(row, dict):raise RecipeError('category', 'Некорректная категория.')
            identifier(row.get('id'), 'category')
            key = row['id'].casefold()
            name = row.get('name')
            if key in seen or not isinstance(name, str) or not name.strip() or any(c in name for c in '\r\n\x00'):
                raise RecipeError('category', 'Повторяющийся код или пустое название категории.')
            binding = stock_binding(row)
            if binding is not None:
                if binding not in STOCK or binding in bindings:
                    raise RecipeError('category', 'Некорректная или повторная привязка к Gothic.')
                bindings.add(binding)
            try:name.encode('cp1251')
            except UnicodeEncodeError as exc:raise RecipeError('category', 'Название категории несовместимо с Windows-1251.') from exc
            seen.add(key)
        return rows

    def save(self, rows):
        # Validate the candidate using the same parser without publishing bad data.
        candidate = RecipeCategories.__new__(RecipeCategories)
        candidate.files = self.files
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from uuid import uuid4
        temporary = self.path.with_name('.categories-' + uuid4().hex + '.tmp')
        candidate.path = temporary
        try:
            temporary.write_text(json.dumps({'schema_version': 1, 'categories': rows}, ensure_ascii=False, indent=2), 'utf-8')
            candidate.load()
            temporary.replace(self.path)
        finally:temporary.unlink(missing_ok=True)

    def validate(self, recipe):
        category = recipe.get('category', '')
        if category and category not in {row['id'] for row in self.load()}:
            raise RecipeError('category', f'Рецепт {recipe["id"]}: неизвестная категория {category}.')

    def free_id(self, base):
        used = {row['id'].casefold() for row in self.load()}
        code, index = base, 1
        while code.casefold() in used:
            code = f'{base}_{index}'
            index += 1
        return code

    def change(self, previous, replacement):
        """Publish category changes and all affected recipe links as one transaction."""
        from .recipes import RecipeStore
        from .artifact_transaction import publish_files
        import tempfile
        rows = self.load()
        old = next((row for row in rows if row['id'] == previous), None)
        if previous is not None and old is None:raise RecipeError('category', 'Категория не найдена.')
        if replacement is not None:
            replacement = deepcopy(replacement)
            if old is not None:replacement['binding'] = stock_binding(old)
            if any(row is not old and row['id'].casefold()==replacement['id'].casefold() for row in rows):
                raise RecipeError('category', 'Код категории уже занят.')
        rows = [replacement if row is old else row for row in rows if row is not old or replacement is not None]
        if old is None and replacement is not None:rows.append(replacement)
        store = RecipeStore(self.path.parents[2])
        recipes = store.load()
        with tempfile.TemporaryDirectory(prefix='recipe-categories-') as temporary:
            stage = Path(temporary)
            candidate = RecipeCategories(stage)
            candidate.save(rows)
            pairs = [(candidate.path, self.path)]
            for index, recipe in enumerate(recipes):
                if previous is None or recipe.get('category') != previous:continue
                recipe['category'] = replacement['id'] if replacement else ''
                source = stage / (str(index)+'.json')
                source.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), 'utf-8')
                pairs.append((source, store.path(recipe['id'])))
            publish_files(pairs)

    def duplicate(self, code):
        original = next(row for row in self.load() if row['id']==code)
        copy = {'id': self.free_id(code+'_copy'), 'name': original['name'], 'binding': None}
        self.change(None, copy)
        return copy
