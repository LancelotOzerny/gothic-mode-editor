"""Stable Daedalus recipe-learning actions shared by books, teachers and scripts.

The game receives ordinary integer constants and a single learning function.
All generated files are staging-only; project data and Gothic scripts stay intact.
"""
from __future__ import annotations

import zlib
import re
from pathlib import Path

from .recipes import RecipeStore
from .daedalus_merge import ScriptTree, definitions, target_path
from .scripts import load_text


ACTION_ID = 'recipe:learn#GE_LearnRecipe'
FUNCTION_NAME = 'GE_LearnRecipe'
OUTPUT = Path('GE_Recipes/Learning.d')


def recipe_code(recipe_id):
    """Stable positive Daedalus int, independent of recipe ordering."""
    return (zlib.crc32(recipe_id.casefold().encode('ascii')) & 0x7fffffff) or 1


def learnable_recipes(project):
    recipes = [recipe for recipe in RecipeStore(project).load()
               if recipe['availability']['type'] == 'global_variable']
    numbers = {}
    for recipe in recipes:
        number = recipe_code(recipe['id'])
        if number in numbers:
            raise ValueError('Конфликт числовых кодов изучения рецептов: ' +
                             numbers[number] + ' / ' + recipe['id'])
        numbers[number] = recipe['id']
    return recipes


def recipe_options(project):
    return tuple((recipe['name'] + ' — ' + recipe['id'], str(recipe_code(recipe['id'])))
                 for recipe in learnable_recipes(project))


def prepare_recipe_learning(project, content):
    """Write learning script before action wrappers are generated."""
    recipes = learnable_recipes(project)
    if not recipes:
        return None
    tree = ScriptTree(content)
    declarations = []
    variables = set()
    for recipe in recipes:
        variable = recipe['availability']['variable']
        key = variable.casefold()
        if key not in variables:
            previous = tree.unique(variable)
            if previous:
                path, definition = previous
                block = tree.documents[path].text[definition.start:definition.end]
                if (definition.kind != 'var' or
                        not re.match(r'var\s+int\s+', block, re.I) or
                        '[' in block):
                    raise ValueError(f'{variable}: требуется скалярная глобальная var int')
            else:
                declarations.append(f'var int {variable};')
            variables.add(key)
        constant = 'GE_RECIPE_' + recipe['id']
        if tree.unique(constant):
            raise ValueError('Конфликт константы изучения: ' + constant)
        declarations.append(f'const int {constant} = {recipe_code(recipe["id"])};')
    cases = '\n'.join(
        '    if (recipe == GE_RECIPE_' + recipe['id'] + ') { ' +
        recipe['availability']['variable'] + ' = TRUE; };'
        for recipe in recipes)
    body = ('// @INFO NAME="Изучить рецепт"\n'
            '// @PARAM VALUE=recipe NAME="Рецепт"\n'
            'func void GE_LearnRecipe(var int recipe) {\n' +
            cases + '\n};\n')
    data = '\n'.join(declarations) + '\n\n' + body
    for definition in definitions(data, 'Recipe learning'):
        for symbol in definition.names:
            if tree.unique(symbol):
                raise ValueError('Конфликт символа изучения рецептов: ' + symbol)
    destination = target_path(content, OUTPUT)
    if destination.exists():
        raise ValueError('Занят путь автогенерации: ' + str(OUTPUT))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data.encode('cp1251'))
    return OUTPUT


def prioritize_learning(manifest):
    """Ensure learning definitions precede action wrappers in Gothic.src."""
    source, encoding = load_text(manifest)
    lines = source.splitlines()
    name = OUTPUT.as_posix().casefold()
    matches = [line for line in lines if line.strip().replace('\\', '/').casefold() == name]
    if not matches:
        raise ValueError('Gothic.src не содержит созданный скрипт изучения рецептов.')
    lines = [line for line in lines if line not in matches]
    # After existing stock includes, but ahead of generated item actions.
    index = next((i for i, line in enumerate(lines)
                  if 'ge_componentpotions.d' in line.casefold() or
                  'ge_actionscripts' in line.casefold()), len(lines))
    lines.insert(index, matches[0])
    manifest.write_text('\r\n'.join(lines) + '\r\n', encoding=encoding, newline='')
