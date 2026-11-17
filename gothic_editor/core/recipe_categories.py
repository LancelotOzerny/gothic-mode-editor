"""Project alchemy menu categories and stock Gothic bindings."""
import json
from pathlib import Path
from copy import deepcopy
from .recipes import identifier, RecipeError
from .asset_files import AssetFiles

STOCK = {'health': 'Health', 'mana': 'Mana', 'special': 'Special', 'booze': 'Booze', 'tabak': 'Tabak'}
DEFAULTS = [{'id': key, 'name': name} for key, name in zip(STOCK,
    ('Зелья здоровья', 'Зелья маны', 'Особые зелья', 'Алкоголь', 'Табак'))]


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
        rows, seen = data['categories'], set()
        for row in rows:
            if not isinstance(row, dict):raise RecipeError('category', 'Некорректная категория.')
            identifier(row.get('id'), 'category')
            key = row['id'].casefold()
            name = row.get('name')
            if key in seen or not isinstance(name, str) or not name.strip() or any(c in name for c in '\r\n\x00'):
                raise RecipeError('category', 'Повторяющийся код или пустое название категории.')
            if key in STOCK and row['id'] != key:
                raise RecipeError('category', 'Коды штатных категорий нельзя менять.')
            try:name.encode('cp1251')
            except UnicodeEncodeError as exc:raise RecipeError('category', 'Название категории несовместимо с Windows-1251.') from exc
            seen.add(key)
        if not set(STOCK) <= seen:raise RecipeError('category', 'Штатные категории нельзя удалять.')
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
