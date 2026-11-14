"""Attach scroll actions to native spell casting in the temporary script tree."""
import re

from .daedalus_merge import declaration_text
from .scripts import mask_comments,replace_field


def _definition(tree,name,kind=None):
    location=tree.unique(name,kind)
    if location is None:raise ValueError(f'Для магических действий свитков требуется {name}.')
    path,definition=location
    return path,definition,declaration_text(tree.documents[path].text,definition)


def _integer(tree,value,seen=()):
    value=value.strip()
    if re.fullmatch(r'[+-]?\d+',value):return int(value)
    if value.casefold() in seen:raise ValueError('Циклическая константа заклинания: '+value)
    _,_,source=_definition(tree,value,'const')
    match=re.search(r'=\s*([^;]+);',mask_comments(source))
    if match is None:raise ValueError('Не удалось определить ID заклинания: '+value)
    return _integer(tree,match[1],seen+(value.casefold(),))


def _array(tree,name):
    path,definition,source=_definition(tree,name,'const')
    matches=list(re.finditer(r'"(?:\\.|[^"\\])*"',mask_comments(source)))
    return path,definition,source,matches


def configure_scroll_cast(items,handlers,tree,changes):
    active=[item for item in items if item.instance.casefold() in handlers]
    if not active:return []
    names_path,names_def,names_source,names=_array(tree,'spellFxInstanceNames')
    code='\n'.join(mask_comments(document.text) for document in tree.documents.values())
    custom=active
    custom_slots={}
    generated=[]
    ani_path,ani_def,ani_source,letters=_array(tree,'spellFxAniLetters')
    used_ids=set()
    for assignment in re.finditer(r'\bspell\s*=\s*([^;]+);',code,re.I):
        try:used_ids.add(_integer(tree,assignment[1]))
        except ValueError:pass
    candidates=re.findall(r'\bconst\s+int\s+(SPL_Reserved_\d+)\s*=\s*(\d+)\s*;',code,re.I)
    free=[]
    for symbol,number in sorted(candidates,key=lambda pair:int(pair[1]),reverse=True):
        number=int(number)
        if (number>=len(names) or number>=len(letters)
                or names[number][0].strip('"').casefold()!='light'
                or letters[number][0].strip('"').upper()!='XXX'):continue
        if len(re.findall(r'\b'+re.escape(symbol)+r'\b',code,re.I))!=1:continue
        if number in used_ids:continue
        free.append(number)
    if len(free)<len(custom):raise ValueError('Недостаточно свободных SPL_Reserved для свитков с действиями; существующие заклинания не заменены.')
    for item,slot in zip(sorted(custom,key=lambda value:value.instance.casefold()),free):
        custom_slots[item.instance.casefold()]=slot
        changes[names_path].append((names_def.start+names[slot].start(),names_def.start+names[slot].end(),'"GE_ItemActions"'))
        changes[ani_path].append((ani_def.start+letters[slot].start(),ani_def.start+letters[slot].end(),'"LGT"'))
    mana_path,mana_def,mana_source=_definition(tree,'Spell_ProcessMana','func')
    condition=' || '.join(f'(Npc_GetActiveSpell(self) == {slot})' for slot in custom_slots.values())
    prefix=(f'\n    if ({condition})\n    {{\n'
            '        if (self.attribute[ATR_MANA] >= SPL_Cost_Scroll) { return SPL_SENDCAST; };\n'
            '        return SPL_SENDSTOP;\n    };\n')
    opening=mask_comments(mana_source).find('{')
    if opening<0:raise ValueError('Некорректная Spell_ProcessMana.')
    changes[mana_path].append((mana_def.start,mana_def.end,mana_source[:opening+1]+prefix+mana_source[opening+1:]))
    generated.append('''INSTANCE Spell_GE_ItemActions(C_Spell_Proto)
{
time_per_mana = 0;
damage_per_level = 0;
spellType = SPELL_GOOD;
targetCollectAlgo = TARGET_COLLECT_CASTER;
targetCollectType = TARGET_TYPE_NPCS;
};
func void Spell_Cast_GE_ItemActions()
{
self.attribute[ATR_MANA] = self.attribute[ATR_MANA] - SPL_Cost_Scroll;
GE_DispatchScrollActions();
self.aivar[AIV_SelectSpell] += 1;
};''')
    dispatch=['func void GE_DispatchScrollActions()','{',
              '    if (!Npc_GetActiveSpellIsScroll(self)) { return; };',
              '    var int GE_SpellId;',
              '    GE_SpellId = Npc_GetActiveSpell(self);']
    for item in active:
        handler=handlers[item.instance.casefold()]
        path,definition,block=_definition(tree,item.instance,'instance')
        flags=item.fields.get('flags','').strip()
        block=replace_field(block,'flags',f'({flags}) | ITEM_MULTI' if flags else 'ITEM_MULTI')
        slot=custom_slots[item.instance.casefold()]
        dispatch.append(f'    if (GE_SpellId == {slot}) {{ {handler}(); return; }};')
        block=replace_field(block,'spell',str(slot))
        block=replace_field(block,'mag_circle','0')
        changes[path].append((definition.start,definition.end,block))
    dispatch.append('};')
    generated.append('\n'.join(dispatch))
    return generated
