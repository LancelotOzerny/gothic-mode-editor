"""Scroll action metadata and callbacks use the existing script-based item store."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from gothic_editor.core.scripts import parse_items,load_text
from gothic_editor.core.item_spreadsheet import export_items,ItemSpreadsheetService
from test_function_actions import ActionFixture,SCHEMA


class ScrollActionTests(ActionFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        base=self.content/'Items/Base.d'
        base.write_text(base.read_text().replace('var func on_state[4];',
            'var func on_state[4]; var int flags; var int spell; var int mag_circle;'))
        self.magic=self.content/'Items/Magic.d'
        source='''
const int ITEM_KAT_RUNE = 512;
const int ITEM_MULTI = 2097152;
const int ITEM_ACTIVE = 1073741824;
const int SPL_Reserved_99 = 99;
const int SPL_Reserved_98 = 98;
const int SPL_Cost_Scroll = 5;
const int ATR_MANA = 2;
const int AIV_SelectSpell = 0;
const int SPL_SENDCAST = 2;
const int SPL_SENDSTOP = 3;
const int SPELL_GOOD = 0;
const int TARGET_COLLECT_CASTER = 1;
const int TARGET_TYPE_NPCS = 4;
const int MAX_SPELL = 100;
class C_Npc { var int attribute[8]; var int aivar[100]; var int padding[92]; };
instance self(C_Npc) { attribute[ATR_MANA]=100; };
instance item(C_Item) { value=0; };
class C_Spell { var float time_per_mana; var int damage_per_level; var int damageType;
var int spellType; var int canTurnDuringInvest; var int canChangeTargetDuringInvest;
var int isMultiEffect; var int targetCollectAlgo; var int targetCollectType;
var int targetCollectRange; var int targetCollectAzi; var int targetCollectElev; };
prototype C_Spell_Proto(C_Spell) {};
func int Spell_ProcessMana(var int manaInvested) { return SPL_SENDSTOP; };
func void Spell_Cast_Light() { TotalExp += 1; };
'''
        source+='const string spellFxInstanceNames[MAX_SPELL] = {'+','.join(['"Light"']*100)+'};\n'
        source+='const string spellFxAniLetters[MAX_SPELL] = {'+','.join(['"XXX"']*100)+'};\n'
        self.magic.write_text(source)

    def scroll(self,name='ItSc_Test'):
        return self.repo._write_new(name,f'INSTANCE {name}(C_Item) {{name="Scroll"; mainflag=ITEM_KAT_RUNE; on_state[0]=Previous;}};')

    def test_metadata_save_reopen_duplicate_and_rename(self):
        item=self.scroll()
        updated=self.assign(item,100)
        self.assertIn('// @GE_METADATA ',updated.text)
        expected=json.loads(updated.editor_metadata['item_actions'])
        self.repo.open(self.repo.root)
        reopened=next(item for item in self.repo.items if item.instance=='ItSc_Test')
        self.assertEqual(json.loads(reopened.editor_metadata['item_actions']),expected)
        copied=self.repo.duplicate(reopened)
        renamed=self.repo.edit(copied,{},instance='ItSc_Renamed')
        self.assertEqual(json.loads(renamed.editor_metadata['item_actions']),expected)
        self.assertEqual(renamed.fields['on_state[0]'],'Previous')

    def test_two_scrolls_in_shared_source_keep_independent_metadata_and_helpers(self):
        path=self.repo._project_content()/'Items/Scrolls.d'
        path.write_text('func void KeepHelper() {};\n'
                        'INSTANCE ItSc_A(C_Item) {mainflag=ITEM_KAT_RUNE;};\n'
                        'INSTANCE ItSc_B(C_Item) {mainflag=ITEM_KAT_RUNE;};',encoding='cp1251')
        self.repo.refresh()
        first,second=parse_items(path,'project')
        self.assign(first,100)
        self.assign(parse_items(path,'project')[1],500)
        self.repo.edit(parse_items(path,'project')[0],{'name':'"Changed"'})
        values=parse_items(path,'project')
        self.assertEqual(json.loads(values[0].editor_metadata['item_actions'])[0]['values'],{'exp':'100'})
        self.assertEqual(json.loads(values[1].editor_metadata['item_actions'])[0]['values'],{'exp':'500'})
        self.assertIn('func void KeepHelper()',load_text(path)[0])

    def test_scroll_only_project_builds_and_keeps_source_callback_unchanged(self):
        self.repo.delete(self.item)
        scroll=self.assign(self.scroll(),100)
        source=scroll.path.read_bytes()
        content,_,_=self.prepare()
        staged=parse_items(content/scroll.path.relative_to(self.repo._project_content()),'project')[0]
        self.assertEqual(staged.fields['on_state[0]'],'Previous')
        self.assertEqual(staged.fields['mainflag'],'ITEM_KAT_RUNE')
        self.assertEqual(staged.fields['spell'],'99')
        self.assertIn('ITEM_MULTI',staged.fields['flags'])
        self.assertNotIn('scemename',staged.fields)
        callbacks=(content/'Items/GE_ComponentPotions.d').read_text('cp1251')
        self.assertIn('Previous();',callbacks)
        self.assertIn('AddExperience(100);',callbacks)
        self.assertIn('func void Spell_Cast_GE_ItemActions()',callbacks)
        self.assertIn('GE_SpellId = Npc_GetActiveSpell(self)',callbacks)
        self.assertIn('if (GE_SpellId == 99) { GE_ItemActions_ItSc_Test(); return; }',callbacks)
        self.assertIn('Npc_GetActiveSpell(self) == 99',(content/'Items/Magic.d').read_text())
        self.assertEqual(scroll.path.read_bytes(),source)
        self.assertEqual(parse_items(scroll.path,'project')[0].fields['on_state[0]'],'Previous')

    def test_xlsx_existing_and_new_scroll_keep_actions(self):
        item=self.assign(self.scroll(),500)
        sheet=self.root/'scrolls.xlsx'
        export_items([item],sheet)
        with patch('gothic_editor.core.item_spreadsheet.schema_for',return_value=SCHEMA):
            ItemSpreadsheetService(self.repo).import_file(sheet,'replace')
        current=next(value for value in self.repo.items if value.instance==item.instance)
        self.assertEqual(current.editor_metadata,item.editor_metadata)
        new=self.repo.create_item_from_fields('ItSc_New',dict(item.fields),item.editor_metadata)
        self.assertEqual(new.editor_metadata,item.editor_metadata)

    def test_multiple_custom_scrolls_get_distinct_spell_ids(self):
        first=self.assign(self.scroll('ItSc_First'),100)
        second=self.assign(self.scroll('ItSc_Second'),500)
        content,_,_=self.prepare()
        one=parse_items(content/first.path.relative_to(self.repo._project_content()),'project')[0]
        two=parse_items(content/second.path.relative_to(self.repo._project_content()),'project')[0]
        self.assertEqual((one.fields['spell'],two.fields['spell']),('99','98'))
        code=(content/'Items/GE_ComponentPotions.d').read_text('cp1251')
        self.assertIn('if (GE_SpellId == 99) { GE_ItemActions_ItSc_First(); return; }',code)
        self.assertIn('if (GE_SpellId == 98) { GE_ItemActions_ItSc_Second(); return; }',code)

    def test_actions_replace_old_spell_only_in_staging_and_leave_other_scrolls_alone(self):
        scroll=self.repo.edit(self.scroll(),{'spell':'18'})
        self.assign(scroll,100)
        ordinary=self.repo.edit(self.scroll('ItSc_Ordinary'),{'spell':'18'})
        original=self.magic.read_bytes()
        content,_,_=self.prepare()
        staged=parse_items(content/scroll.path.relative_to(self.repo._project_content()),'project')[0]
        self.assertEqual(staged.fields['spell'],'99')
        self.assertEqual(parse_items(scroll.path,'project')[0].fields['spell'],'18')
        untouched=parse_items(content/ordinary.path.relative_to(self.repo._project_content()),'project')[0]
        self.assertEqual(untouched.fields['spell'],'18')
        code=(content/'Items/Magic.d').read_text()
        self.assertNotIn('GE_DispatchScrollActions();',code)
        self.assertIn('TotalExp += 1;',code)
        self.assertIn('Npc_GetActiveSpell(self) == 99',code)
        self.assertEqual(self.magic.read_bytes(),original)

    def test_reserved_id_in_use_is_not_replaced(self):
        with self.magic.open('a') as stream:
            stream.write('\nINSTANCE OtherScroll(C_Item) { spell=99; };\n')
        scroll=self.assign(self.scroll(),100)
        content,_,_=self.prepare()
        staged=parse_items(content/scroll.path.relative_to(self.repo._project_content()),'project')[0]
        self.assertEqual(staged.fields['spell'],'98')

    def test_removing_actions_restores_original_spell_without_cast_changes(self):
        scroll=self.assign(self.repo.edit(self.scroll(),{'spell':'18'}),100)
        self.repo.edit(scroll,{},metadata={'item_actions':'[]'})
        original=self.magic.read_bytes()
        content,_,_=self.prepare()
        staged=parse_items(content/scroll.path.relative_to(self.repo._project_content()),'project')[0]
        self.assertEqual(staged.fields['spell'],'18')
        self.assertEqual((content/'Items/Magic.d').read_bytes(),original)

    def test_insufficient_reserved_slots_fail_without_changing_sources(self):
        for name in ('ItSc_First','ItSc_Second','ItSc_Third'):self.assign(self.scroll(name),100)
        original=self.magic.read_bytes()
        with self.assertRaisesRegex(ValueError,'Недостаточно свободных'):self.prepare()
        self.assertEqual(self.magic.read_bytes(),original)

    @unittest.skipUnless(os.environ.get('GOTHIC_TEST_COMPILER'),'Optional real GDC')
    def test_real_compiler_accepts_scroll_and_potion_callbacks(self):
        from gothic_editor.core.compiler_runner import run_compiler
        self.assign(self.item,100)
        self.assign(self.scroll(),500)
        self.assign(self.repo.edit(self.scroll('ItSc_Existing'),{'spell':'18'}),1000)
        content,manifest,_=self.prepare()
        output=content.parent/'Gothic.dat'
        log=content.parent/'compiler.log'
        result=run_compiler([os.environ['GOTHIC_TEST_COMPILER'],str(manifest),'--output-dat',str(output)],content.parent,log)
        self.assertEqual(result.returncode,0,log.read_text('utf-8'))
        self.assertTrue(output.stat().st_size)
