"""Versioned project recipes; no game files are written by this store."""
import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path

MAX_INT = 2147483647
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]*\Z')


class RecipeError(ValueError):
    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


def identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise RecipeError(field, 'Нужен идентификатор Daedalus: латиница, цифры, подчёркивание.')


def quantity(value, field):
    if type(value) is not int or not 1 <= value <= MAX_INT:
        raise RecipeError(field, f'Нужно целое число от 1 до {MAX_INT}.')


def validate_recipe(data):
    if not isinstance(data, dict):
        raise RecipeError('id', 'Рецепт должен быть JSON-объектом.')
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise RecipeError('id', 'Неподдерживаемая версия рецепта.')
    identifier(data.get('id'), 'id')
    if data.get('category', '') != '':identifier(data['category'], 'category')
    name = data.get('name')
    if not isinstance(name, str) or not name.strip() or any(c in name for c in '\r\n\x00'):
        raise RecipeError('name', 'Укажите непустое название одной строкой.')
    try:
        name.encode('cp1251')
    except UnicodeEncodeError as exc:
        raise RecipeError('name', 'Название не представимо в Windows-1251.') from exc
    identifier(data.get('result'), 'result')
    quantity(data.get('result_count'), 'result_count')
    ingredients = data.get('ingredients')
    if not isinstance(ingredients, list) or not ingredients:
        raise RecipeError('ingredients', 'Добавьте хотя бы один ингредиент.')
    seen = set()
    for row in ingredients:
        if not isinstance(row, dict):
            raise RecipeError('ingredients', 'Некорректная строка ингредиента.')
        identifier(row.get('instance'), 'ingredients')
        quantity(row.get('count'), 'ingredients')
        key = row['instance'].casefold()
        if key in seen:
            raise RecipeError('ingredients', 'Ингредиент повторяется: объедините количество в одной строке.')
        seen.add(key)
    availability = data.get('availability')
    if not isinstance(availability, dict) or availability.get('type') not in ('always', 'global_variable', 'stock_talent'):
        raise RecipeError('availability', 'Неизвестный способ доступности.')
    if availability['type'] == 'global_variable':
        identifier(availability.get('variable'), 'variable')
    elif availability['type'] == 'stock_talent':
        identifier(availability.get('talent'), 'availability')
    return data


def batch_requirements(recipe, portions):
    """Validate multiplication before any inventory operation (also used by generation)."""
    validate_recipe(recipe)
    quantity(portions, 'portions')
    counts = [recipe['result_count']] + [row['count'] for row in recipe['ingredients']]
    if any(portions > MAX_INT // count for count in counts):
        raise RecipeError('portions', 'Переполнение игрового целого числа.')
    return ({row['instance']: row['count'] * portions for row in recipe['ingredients']},
            recipe['result_count'] * portions)


class RecipeStore:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.root = self.project / 'Assets/Recipes/Alchemy'

    def checked(self, path):
        if not path.resolve().is_relative_to(self.project) or not path.resolve().is_relative_to(self.root.resolve()):
            raise RecipeError('id', f'Небезопасный путь рецепта: {path}')
        return path

    def path(self, code):
        identifier(code, 'id')
        if code.upper() in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(COM|LPT)[1-9]', code, re.I):
            raise RecipeError('id', 'Зарезервированное имя файла Windows.')
        return self.checked(self.root / (code + '.json'))

    def load(self):
        self.checked(self.root)
        result, seen = [], set()
        for path in sorted(self.root.rglob('*')):
            self.checked(path)
            if not path.is_file() or path.suffix.casefold() != '.json':
                continue
            try:
                data = validate_recipe(json.loads(path.read_text('utf-8')))
                if self.path(data['id']) != path:
                    raise RecipeError('id', 'Имя файла должно совпадать с ID рецепта.')
                if data['id'].casefold() in seen:
                    raise RecipeError('id', 'Повторяющийся ID рецепта.')
                seen.add(data['id'].casefold())
                result.append(data)
            except (ValueError, UnicodeError) as exc:
                raise RecipeError(getattr(exc, 'field', 'id'), f'{path}: {exc}') from exc
        return result

    def save(self, data, previous=None):
        validate_recipe(data)
        from .recipe_categories import RecipeCategories
        RecipeCategories(self.project).validate(data)
        destination = self.path(data['id'])
        for recipe in self.load():
            if recipe['id'].casefold() == data['id'].casefold() and recipe['id'] != previous:
                raise RecipeError('id', 'ID рецепта уже занят.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(destination)
            if previous and previous.casefold() != data['id'].casefold():
                self.path(previous).unlink()
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def free_id(self, base='RECIPE_NEW'):
        used = {r['id'].casefold() for r in self.load()}
        code, index = base, 1
        while code.casefold() in used:
            code = f'{base}_{index}'
            index += 1
        return code

    def duplicate(self, recipe):
        data = deepcopy(recipe)
        data['id'] = self.free_id(recipe['id'] + '_copy')
        self.save(data)
        return data

    def delete(self, code):
        self.path(code).unlink()
