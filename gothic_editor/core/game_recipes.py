"""Read ordinary stock alchemy recipes as independent editable templates."""
import re
from .scripts import load_text, mask_comments, block_end
from .daedalus_merge import definitions
from .recipe_categories import STOCK
from .recipes import validate_recipe


def game_recipes(game):
    if game is None:raise ValueError('Укажите папку Gothic в настройках проекта.')
    content = game / '_work/Data/Scripts/Content'
    path = next((p for p in content.rglob('*.d') if p.name.casefold()=='potion_alchemy.d'), None)
    if path is None:raise ValueError('Не найден исходный скрипт Potion_Alchemy.d в Gothic.')
    text = mask_comments(load_text(path)[0])
    blocks = {name.casefold(): (definition.kind, text[definition.start:definition.end])
              for definition in definitions(text, str(path)) for name in definition.names}
    end = blocks.get('pc_potionalchemy_end_info', ('',''))[1]
    flask = re.search(r'CreateInvItems\s*\(\s*self\s*,\s*(\w+)\s*,\s*1\s*\)', end, re.I)
    if flask is None:raise ValueError('Не удалось определить предмет, удерживаемый алхимическим столом.')
    results, skipped = [], []
    call = r'\b%s\s*\(\s*(?:self|hero)\s*,\s*([A-Za-z_]\w*)\s*,\s*([0-9]+)\s*\)\s*;'
    for code, (kind, block) in blocks.items():
        if kind != 'instance' or not re.search(r'\(\s*C_Info\s*\)', block, re.I):continue
        info = re.search(r'\binformation\s*=\s*(\w+)\s*;', block, re.I)
        condition = re.search(r'\bcondition\s*=\s*(\w+)\s*;', block, re.I)
        if info is None or condition is None:continue
        body = blocks.get(info[1].casefold(), ('',''))[1]
        if not re.search(r'\bNpc_RemoveInvItems\s*\(', body, re.I):continue
        try:
            condition_body = blocks.get(condition[1].casefold(), ('',''))[1]
            category = next((key for key, value in STOCK.items() if re.search(r'\b'+value+r'Start\s*==\s*TRUE\b', condition_body, re.I)), None)
            if category is None:raise ValueError('Неизвестная категория')
            # Only the success branch is copied; no arbitrary script is executed.
            start = body.index('{', body.index('{')+1)
            stop = block_end(body, start)
            success = body[start:stop]
            removals = re.findall(call % 'Npc_RemoveInvItems', success, re.I)
            products = re.findall(call % 'CreateInvItems', success, re.I)
            single = r'\bCreateInvItem\s*\(\s*(?:self|hero)\s*,\s*([A-Za-z_]\w*)\s*\)\s*;'
            products += [(name, '1') for name in re.findall(single, success, re.I)]
            checks = re.findall(r'Npc_HasItems\s*\(\s*(?:self|hero)\s*,\s*(\w+)\s*\)\s*>=\s*([0-9]+)', body[:start], re.I)
            if (len(products)!=1 or not removals or len(removals)!=len(re.findall(r'\bNpc_RemoveInvItems\s*\(', body, re.I))
                    or sorted((a.casefold(),b) for a,b in checks)!=sorted((a.casefold(),b) for a,b in removals)):
                raise ValueError('Нестандартные проверки или изготовление')
            # Refuse branches with extra effects rather than silently dropping them.
            stripped = re.sub(call % 'Npc_RemoveInvItems', '', success, flags=re.I)
            stripped = re.sub(call % 'CreateInvItems', '', stripped, flags=re.I)
            stripped = re.sub(single, '', stripped, flags=re.I)
            stripped = re.sub(r'Print\s*\(\s*PRINT_AlchemySuccess\s*\)\s*;', '', stripped, flags=re.I)
            if stripped.strip(' \t\r\n{};'):raise ValueError('Дополнительная логика рецепта')
            title = re.search(r'\bdescription\s*=\s*"((?:\\.|[^"\\])*)"\s*;', block, re.I)
            if title is None:raise ValueError('Название задано выражением')
            ingredients = [{'instance': name, 'count': int(count)} for name,count in removals]
            # The stock mob consumes one held flask before entering the dialog.
            existing = next((r for r in ingredients if r['instance'].casefold()==flask[1].casefold()), None)
            if existing:existing['count'] += 1
            else:ingredients.append({'instance': flask[1], 'count': 1})
            recipe = dict(schema_version=1, id='COPY_'+code.upper(), name=title[1], category=category,
                          result=products[0][0], result_count=int(products[0][1]), ingredients=ingredients,
                          availability={'type':'always'})
            results.append(validate_recipe(recipe))
        except (ValueError, StopIteration):skipped.append(code)
    return results, skipped
