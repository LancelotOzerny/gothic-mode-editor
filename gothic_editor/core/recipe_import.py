"""Batch import Gothic alchemy templates into a selected recipe category."""
import json
import tempfile
from copy import deepcopy
from pathlib import Path

from .artifact_transaction import publish_files
from .game_recipes import game_recipes
from .recipe_categories import RecipeCategories, stock_binding
from .recipes import RecipeStore, RecipeError


def import_category_recipes(project, game, category, *, history=None):
    """Import every supported Gothic recipe in the selected category.

    For custom nested categories, use their nearest stock Gothic ancestor as
    the source filter. Existing source IDs are skipped; no files are overwritten.
    Returns (imported_count, existing_count, unsupported_count).
    """
    category_store = RecipeCategories(project)
    categories = {row['id']: row for row in category_store.load()}
    if category not in categories:
        raise RecipeError('category', f'Неизвестная категория: {category}')
    origin = category
    while origin and stock_binding(categories[origin]) is None:
        origin = categories[origin].get('parent') or ''
    if not origin:
        raise RecipeError('category', 'У категории нет исходного раздела Gothic для импорта.')
    binding = stock_binding(categories[origin])
    templates, skipped = game_recipes(game)
    matching = [row for row in templates if row['category'] == binding]
    store = RecipeStore(project)
    existing_ids = {row['id'].casefold() for row in store.load()}
    imported, already = [], 0
    for template in matching:
        # The stock parser assigns a stable COPY_... ID per Gothic C_Info.
        if template['id'].casefold() in existing_ids:
            already += 1
            continue
        data = deepcopy(template)
        data['category'] = category
        category_store.validate(data)
        destination = store.path(data['id'])
        if destination.exists():
            already += 1
            continue
        existing_ids.add(data['id'].casefold())
        imported.append((data, destination))
    if imported:
        paths = [path for _, path in imported]
        before = history.capture(paths) if history is not None else None
        with tempfile.TemporaryDirectory(prefix='gothic-recipe-import-') as folder:
            staged = []
            for index, (data, destination) in enumerate(imported):
                source = Path(folder) / f'{index}.json'
                source.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
                staged.append((source, destination))
            publish_files(staged)
        if history is not None:
            history.record(before)
    return len(imported), already, len(skipped)
