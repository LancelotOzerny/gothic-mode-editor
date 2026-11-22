"""Alchemy dialogs generated exclusively in the merged staging source tree."""
import fnmatch
import re
from pathlib import Path

from .daedalus_merge import ScriptTree, definitions, target_path
from .scripts import load_text, mask_comments
from .recipes import RecipeStore, MAX_INT, batch_requirements
from .recipe_categories import RecipeCategories, STOCK, DEFAULTS, stock_binding


def included_scripts(manifest, root):
    files, visited = set(), set()

    def visit(path):
        if path in visited:
            return
        visited.add(path)
        source, _ = load_text(path)
        for line in mask_comments(source).splitlines():
            pattern = line.strip().replace('\\', '/')
            if not pattern:
                continue
            matches = [path.parent]
            for part in pattern.split('/'):
                if part in ('', '.'):
                    continue
                if part == '..':
                    matches = [p.parent for p in matches]
                else:
                    matches = [c for p in matches if p.is_dir() for c in p.iterdir()
                               if fnmatch.fnmatchcase(c.name.casefold(), part.casefold())]
            for match in matches:
                if not match.resolve().is_relative_to(root.resolve()):
                    raise ValueError(f'Небезопасный путь Gothic.src: {match}')
                if match.suffix.casefold() == '.src':
                    visit(match)
                elif match.is_file():
                    files.add(match)
    visit(manifest)
    return files


def literal(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def apply_recipes(project, content, manifest):
    recipes = RecipeStore(project).load()
    category_store = RecipeCategories(project)
    categories = category_store.load()
    bindings = {row['id']: stock_binding(row) for row in categories}
    if not recipes and categories == DEFAULTS:
        return []
    for recipe in recipes:category_store.validate(recipe)
    tree = ScriptTree(content)
    active = included_scripts(manifest, content)
    tree.symbols = {key: [(p, d) for p, d in rows if p in active]
                    for key, rows in tree.symbols.items()}

    def source(name, kind):
        location = tree.unique(name, kind)
        if location is None:
            raise ValueError(f'В Gothic.src отсутствует {name} ({kind}).')
        path, definition = location
        return tree.documents[path].text[definition.start:definition.end]

    # This adapter targets the shipped G2/NotR interaction, including the flask
    # held by the mob. Reject incompatible overlays rather than guessing hooks.
    source('POTIONALCHEMY_S1', 'func')
    end = source('PC_PotionAlchemy_End_Info', 'func')
    flask = re.search(r'CreateInvItems\s*\(\s*self\s*,\s*(\w+)\s*,\s*1\s*\)', mask_comments(end), re.I)
    if flask is None or 'b_endproductiondialog' not in end.casefold():
        raise ValueError('Рецепты: неподдерживаемый обработчик выхода алхимического стола.')
    condition = source('PC_PotionAlchemy_End_Condition', 'func')
    if 'mobsi_potionalchemy' not in condition.casefold():
        raise ValueError('Рецепты: не найдено штатное условие алхимического стола.')
    # Reuse the original main-menu condition: stock submenus stay separate.
    source('B_ENDPRODUCTIONDIALOG', 'func')
    declarations, bodies, generated = [], [], set()
    custom = {}
    category_index = {row['id']: row for row in categories}
    children = {row['id']: [] for row in categories}
    for row in categories:
        parent = row.get('parent') or ''
        if parent:
            children[parent].append(row['id'])

    def menu_root(code):
        """The first custom C_Info immediately under a stock or root menu."""
        while category_index[code].get('parent'):
            parent = category_index[code]['parent']
            if bindings[parent] is not None:
                break
            code = parent
        return code

    edits = {}
    for category in categories:
        key = category['id']
        binding = bindings[key]
        if binding is not None:
            if category['name'] != next(row['name'] for row in DEFAULTS if row['id'] == binding):
                path, definition = tree.unique('PC_' + STOCK[binding] + '_Start', 'instance')
                block = source('PC_' + STOCK[binding] + '_Start', 'instance')
                replaced, count = re.subn(r'\bdescription\s*=\s*"(?:\\.|[^"\\])*"\s*;',
                    lambda _: 'description = ' + literal(category['name']) + ';', block, flags=re.I)
                if count != 1:raise ValueError('Не удалось изменить название категории ' + key)
                edits.setdefault(path, []).append((definition.start, definition.end, replaced))
        else:custom[key] = []
    for recipe in recipes:
        try:
            batch_requirements(recipe, 1)
            for name in [recipe['result']] + [r['instance'] for r in recipe['ingredients']]:
                block = source(name, 'instance')
                if not re.match(r'instance\s+\w+\s*\(\s*C_Item\s*\)', block, re.I):
                    raise ValueError(f'{name} не является C_Item.')
            availability = recipe['availability']
            known = 'TRUE'
            if availability['type'] == 'global_variable':
                variable = availability['variable']
                location = tree.unique(variable)
                if location:
                    block = source(variable, 'var')
                    if not re.match(r'var\s+int\s+', block, re.I) or '[' in block:
                        raise ValueError(f'{variable}: нужна скалярная глобальная var int.')
                elif variable.casefold() not in generated:
                    declarations.append(f'var int {variable};')
                    generated.add(variable.casefold())
                known = f'({variable} != 0)'
            prefix = 'GE_Recipe_' + recipe['id']
            category = recipe.get('category', '')
            menu_condition = 'PC_PotionAlchemy_End_Condition()'
            clear_choices = ''
            if bindings.get(category) is not None:
                function = 'PC_' + STOCK[bindings[category]] + '_Stop_Condition'
                source(function, 'func')
                menu_condition = function + '()'
            elif category:
                menu_condition = 'FALSE'
                custom[category].append((recipe, known))
                clear_choices = 'Info_ClearChoices(GE_RecipeCategory_' + menu_root(category) + ');'
            craft, cond, info = prefix + '_Craft', prefix + '_Condition', prefix + '_Info'
            limit = min(MAX_INT // n for n in [recipe['result_count']] + [r['count'] for r in recipe['ingredients']])
            checks = '\n'.join(f'if (Npc_HasItems(self, {r["instance"]}) < ({r["count"]} * portions)) {{ return FALSE; }};'
                               for r in recipe['ingredients'])
            remove = '\n'.join(f'Npc_RemoveInvItems(self, {r["instance"]}, {r["count"]} * portions);'
                               for r in recipe['ingredients'])
            bodies.append(f'''func int {craft}(var int portions)
{{
    if (portions <= 0) {{ return FALSE; }};
    if (portions > {limit}) {{ return FALSE; }};
    if (!{known}) {{ return FALSE; }};
    {checks}
    {remove}
    CreateInvItems(self, {recipe['result']}, {recipe['result_count']} * portions);
    return TRUE;
}};
func int {cond}()
{{
    if ({menu_condition}) && {known} {{ return TRUE; }};
    return FALSE;
}};
func void {info}()
{{
    {clear_choices}
    CreateInvItems(self, {flask.group(1)}, 1);
    if ({craft}(1)) {{ Print(PRINT_AlchemySuccess); }}
    else {{ Print(PRINT_ProdItemsMissing); }};
    B_ENDPRODUCTIONDIALOG();
}};
instance {prefix}(C_Info)
{{
    npc = PC_Hero;
    nr = 50;
    condition = {cond};
    information = {info};
    permanent = TRUE;
    description = {literal(recipe['name'])};
}};''')
        except ValueError as exc:
            raise ValueError(f'Рецепт {recipe["id"]}: {exc}') from exc
    # Generate a single C_Info holder for each top-level custom branch.
    # Deeper nodes rebuild choices on that same holder, allowing an arbitrary
    # category depth without requiring engine plugins or new NPC dialogs.
    def known_for(code):
        values = [known for _, known in custom.get(code, ())]
        for child in children[code]:
            values.extend(known_for(child))
        return values

    for category in categories:
        key = category['id']
        if bindings[key] is not None or not known_for(key):
            continue
        prefix = 'GE_RecipeCategory_' + key
        holder = 'GE_RecipeCategory_' + menu_root(key)
        parent = category.get('parent') or ''
        back = (f'GE_RecipeCategory_{parent}_Info();'
                if parent and bindings[parent] is None
                else f'Info_ClearChoices({holder});')
        choices = '\\n'.join(
            f'if ({known}) {{ Info_AddChoice({holder}, {literal(recipe["name"])}, GE_Recipe_{recipe["id"]}_Info); }};'
            for recipe, known in custom.get(key, ())
        )
        child_choices = '\\n'.join(
            f'if ({" || ".join("(" + k + ")" for k in known_for(child))}) '
            f'{{ Info_AddChoice({holder}, {literal(category_index[child]["name"])}, GE_RecipeCategory_{child}_Info); }};'
            for child in children[key] if known_for(child)
        )
        bodies.append(f'''func void {prefix}_Back() {{
    {back}
}};
func void {prefix}_Info() {{
    Info_ClearChoices({holder});
    Info_AddChoice({holder}, DIALOG_BACK, {prefix}_Back);
    {choices}
    {child_choices}
}};''')
        # Only a branch immediately below the root or a stock Gothic group
        # needs its own C_Info instance. All descendants reuse that holder.
        if holder != prefix:
            continue
        stock_parent = bindings[parent] if parent else None
        if stock_parent:
            condition = 'PC_' + STOCK[stock_parent] + '_Stop_Condition()'
            source('PC_' + STOCK[stock_parent] + '_Stop_Condition', 'func')
        else:
            condition = 'PC_PotionAlchemy_End_Condition()'
        available = ' || '.join('(' + known + ')' for known in known_for(key))
        bodies.append(f'''func int {prefix}_Condition() {{
    if ({condition}) && ({available}) {{ return TRUE; }};
    return FALSE;
}};
instance {prefix}(C_Info) {{
    npc = PC_Hero;
    nr = 49;
    condition = {prefix}_Condition;
    information = {prefix}_Info;
    permanent = TRUE;
    description = {literal(category['name'])};
}};''')
    text = '\n'.join(declarations + bodies) + '\n'
    seen = set()
    for definition in definitions(text, 'Рецепты'):
        for name in definition.names:
            key = name.casefold()
            if tree.symbols.get(key) or key in seen:
                raise ValueError(f'Рецепты: конфликт генерируемого символа {name}.')
            seen.add(key)
    relative = Path('GE_Recipes/Alchemy.d')
    destination = target_path(content, relative)
    if destination.exists():
        raise ValueError(f'Рецепты: занят путь {relative}.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(text.encode('cp1251'))
    tree.apply(edits)
    # Last include: item, knowledge-variable and mobsi dependencies precede recipes.
    original, codec = load_text(manifest)
    manifest.write_text(original.rstrip() + '\nGE_Recipes\\Alchemy.d\n', encoding=codec)
    return [relative]
