import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from gothic_editor.core.daedalus_merge import DaedalusMergeError, definitions
from gothic_editor.core.potion_components import PotionComponents
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.compiler_sources import prepare_compiler_sources
from gothic_editor.core.scripts import load_text, parse_items


ORIGINAL = '''// Оригинальные зелья; комментарий INSTANCE Fake(C_Item) {}
const int HP_Essenz = 50;
var int Counter;
INSTANCE ItPo_Health_01(C_Item)
{
    name = "Зелье";
    description = "Лечебная эссенция";
    value = 25;
};
// Второе зелье должно остаться целиком.
INSTANCE ItPo_Health_02(C_Item)
{
    name = "Зелье";
    description = "Лечебный экстракт";
    value = 50;
};
FUNC VOID UseItPo_Health_01()
{
    if (Counter == 0) {
        // Скобки в строке и комментарии не завершают функцию: }
        Print("} /* INSTANCE Hidden(C_Item) { */");
        if (Counter < 2) { Counter = Counter + 1; };
    };
};
// Конец исходного файла.
'''.replace('\n', '\r\n')


class DaedalusBuildMergeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gothic merge ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root/'project'
        self.game = self.root/'game'
        self.source = self.project/'Scripts/Content'
        self.content = self.game/'_work/Data/Scripts/Content'
        self.original = self.content/'ITEMS/IT_Potions.D'
        self.original.parent.mkdir(parents=True)
        (self.source/'items').mkdir(parents=True)
        self.original.write_bytes(ORIGINAL.encode('cp1251'))
        (self.content/'Gothic.src').write_bytes(b'ITEMS\\IT_*.D\r\n')
        self.store = PotionComponents(self.project)
        self.tools = ProjectTools(self.project, self.game)

    def snapshot(self, root):
        return {path.relative_to(root): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob('*') if path.is_file()}

    def prepare(self):
        temporary = tempfile.TemporaryDirectory(prefix='staging-', dir=self.root)
        self.addCleanup(temporary.cleanup)
        return self.tools._prepare(Path(temporary.name), lambda _: None)[0]

    def import_first(self):
        item = parse_items(self.original, 'game')[0]
        self.store.import_item(item)
        copied = self.store.list_items()[0]
        self.store.edit(copied, {'description': '"Изменённое зелье"', 'value': '100'})
        return item

    def test_json_override_keeps_other_instances_helpers_comments_and_cp1251(self):
        self.import_first()
        before = self.snapshot(self.game)
        content = self.prepare()
        merged = content/'ITEMS/IT_Potions.D'
        text, codec = load_text(merged)
        self.assertEqual(codec, 'cp1251')
        items = parse_items(merged, 'build')
        self.assertEqual([item.instance for item in items], ['ItPo_Health_01', 'ItPo_Health_02'])
        self.assertEqual(items[0].fields['description'], '"Изменённое зелье"')
        original_items = parse_items(self.original, 'game')
        self.assertEqual(items[1].text, original_items[1].text)
        suffix = ORIGINAL[ORIGINAL.index('// Второе зелье'):]
        self.assertTrue(text.endswith(suffix))
        self.assertIn('const int HP_Essenz = 50;\r\nvar int Counter;', text)
        self.assertTrue(text.startswith('// Оригинальные зелья;'))
        self.assertEqual(before, self.snapshot(self.game))

    def test_incomplete_unmarked_legacy_copy_cannot_remove_json_target(self):
        self.import_first()
        second = parse_items(self.original, 'game')[1]
        legacy = second.text.replace('value = 50;', 'value = 99;') + ';'
        (self.source/'items/it_potions.d').write_bytes(legacy.encode('cp1251'))
        before = self.snapshot(self.game)
        merged = self.prepare()/'ITEMS/IT_Potions.D'
        items = parse_items(merged, 'build')
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].fields['description'], '"Изменённое зелье"')
        self.assertEqual(items[1].fields['value'], '99')
        self.assertIn('FUNC VOID UseItPo_Health_01()', load_text(merged)[0])
        self.assertEqual(self.snapshot(self.game), before)

    def test_new_json_item_repeated_builds_are_identical_and_do_not_duplicate(self):
        original = self.import_first()
        self.store.import_item(original, 'GE_Health_New')
        before = self.snapshot(self.game)
        first, second = self.prepare(), self.prepare()
        self.assertEqual(self.snapshot(first), self.snapshot(second))
        items = [item for path in first.rglob('*') if path.suffix.casefold()=='.d'
                 for item in parse_items(path, 'build')]
        names = [item.instance.casefold() for item in items]
        self.assertEqual(sorted(names), ['ge_health_new', 'itpo_health_01', 'itpo_health_02'])
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(self.snapshot(self.game), before)

    def test_unmarked_legacy_instance_case_and_extension_case(self):
        original = parse_items(self.original, 'game')[0]
        legacy = original.text.replace('ItPo_Health_01', 'iTpO_hEaLtH_01').replace('value = 25;', 'value = 77;')
        (self.source/'items/it_potions.d').write_bytes((legacy+';').encode('cp1251'))
        merged = self.prepare()/'ITEMS/IT_Potions.D'
        items = parse_items(merged, 'build')
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].fields['value'], '77')
        self.assertEqual(items[1].fields['value'], '50')

    def test_component_compiler_preparation_is_repeatable_and_preserves_include_order(self):
        original = self.import_first()
        self.store.import_item(original, 'GE_Health_New')
        manifest = self.content / 'Gothic.src'
        manifest.write_bytes(b'ITEMS\\IT_*.D\r\nStory\\After.d\r\n')
        (self.content / 'Story').mkdir()
        (self.content / 'Story/After.d').write_bytes(b'func void After() {};\r\n')
        before = self.snapshot(self.game)
        builds = []
        for _ in range(2):
            content = self.prepare()
            prepare_compiler_sources(content, lambda _: None)
            builds.append(self.snapshot(content))
            lines = (content / 'Gothic.src').read_text('utf-8-sig').splitlines()
            self.assertEqual(lines, ['ITEMS\\IT_*.D', 'ITEMS\\GE_ComponentPotions.d', 'Story\\After.d'])
            text, codec = load_text(content / 'ITEMS/IT_Potions.D')
            self.assertEqual(codec, 'cp1251')
            self.assertEqual(len(parse_items(content / 'ITEMS/IT_Potions.D', 'build')), 2)
            self.assertIn('FUNC VOID UseItPo_Health_01()', text)
            for path in content.rglob('*'):
                if path.suffix.lower() in ('.d', '.src'):
                    raw = path.read_bytes()
                    self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
        self.assertEqual(builds[0], builds[1])
        self.assertEqual(self.snapshot(self.game), before)

    def test_new_legacy_instance_can_be_added_to_an_existing_original_file(self):
        (self.source/'items/it_potions.d').write_bytes(
            'INSTANCE GE_New(C_Item) { name = "Новое"; };'.encode('cp1251'))
        merged = self.prepare()/'ITEMS/IT_Potions.D'
        text, codec = load_text(merged)
        self.assertTrue(text.startswith(ORIGINAL))
        self.assertEqual(codec, 'cp1251')
        self.assertEqual(len(parse_items(merged, 'build')), 3)

    def test_ambiguous_original_and_project_definitions_abort(self):
        self.import_first()
        duplicate = self.original.parent/'Duplicate.d'
        duplicate.write_text('INSTANCE itpo_HEALTH_01(C_Item) {};', encoding='utf-8')
        with self.assertRaisesRegex(DaedalusMergeError, 'Неоднозначное.*itpo_health_01'):
            self.prepare()
        duplicate.unlink()
        (self.source/'First.d').write_text('INSTANCE Conflict(C_Item) {};', encoding='utf-8')
        (self.source/'Second.D').write_text('INSTANCE CONFLICT(C_Item) {};', encoding='utf-8')
        with self.assertRaisesRegex(DaedalusMergeError, 'Неоднозначное проектное определение conflict'):
            self.prepare()

    def test_identifier_kind_conflicts_and_partial_group_replacement_abort(self):
        (self.source/'Conflict.d').write_text('const int itpo_health_01 = 1;', encoding='utf-8')
        with self.assertRaisesRegex(DaedalusMergeError, 'Конфликт идентификатора'):
            self.prepare()
        (self.source/'Conflict.d').unlink()
        (self.content/'Vars.d').write_text('var int First, Second;', encoding='utf-8')
        (self.source/'Vars.d').write_text('var int FIRST;', encoding='utf-8')
        with self.assertRaisesRegex(DaedalusMergeError, 'групповое объявление'):
            self.prepare()

    def test_lexer_ignores_fake_declarations_and_preserves_nested_blocks(self):
        parsed = definitions(ORIGINAL, 'original')
        self.assertEqual([definition.names[0] for definition in parsed],
                         ['HP_Essenz', 'Counter', 'ItPo_Health_01', 'ItPo_Health_02', 'UseItPo_Health_01'])
        broken = 'INSTANCE Broken(C_Item) { if (1) { value = 1; };'
        (self.source/'Broken.d').write_text(broken, encoding='utf-8')
        with self.assertRaisesRegex(DaedalusMergeError, 'Незавершённое определение'):
            self.prepare()

    def test_json_function_and_constant_overrides_are_structural(self):
        self.import_first()
        folder = self.store.root/'ItPo_Health_01'
        helper = 'FUNC VOID UseItPo_Health_01() { if (1) { Print("} ;"); }; };'
        (folder/'functions.json').write_text(json.dumps({'source_functions':[
            {'code':'UseItPo_Health_01','source':helper,'override':True}]}), encoding='utf-8')
        (folder/'params.json').write_text(json.dumps({'source_constants':[
            {'code':'HP_Essenz','type':'int','expression':'80','override':True}]}), encoding='utf-8')
        text = load_text(self.prepare()/'ITEMS/IT_Potions.D')[0]
        self.assertIn(helper, text)
        self.assertIn('const int HP_Essenz = 80;', text)
        self.assertIn('// Второе зелье должно остаться целиком.', text)

    def test_new_json_item_cannot_collide_with_original_identifier(self):
        original = parse_items(self.original, 'game')[0]
        self.store.import_item(original, 'iTpo_HEALTH_02')
        before = self.snapshot(self.game)
        with self.assertRaisesRegex(DaedalusMergeError, 'Конфликт идентификатора нового определения'):
            self.prepare()
        self.assertEqual(self.snapshot(self.game), before)

    def test_duplicate_json_component_identifiers_are_rejected(self):
        self.import_first()
        original = self.store.root/'ItPo_Health_01/item.json'
        duplicate = self.store.root/'Other/item.json'
        duplicate.parent.mkdir()
        data = json.loads(original.read_text('utf-8'))
        data['instance'] = data['instance'].upper()
        duplicate.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Неоднозначный INSTANCE'):
            self.prepare()

    def test_legacy_empty_statements_are_not_emitted_with_new_declarations(self):
        legacy = ';\n// Removed old item.\n;\nvar int NewValue;\n;\n'
        (self.source/'items/it_potions.d').write_text(legacy, encoding='utf-8')
        text = load_text(self.prepare()/'ITEMS/IT_Potions.D')[0]
        self.assertIn('// Removed old item.', text)
        self.assertIn('var int NewValue;', text)
        self.assertNotIn('\n;\n', text)

    def test_unchanged_legacy_code_retains_original_comments_and_bytes(self):
        function = next(definition for definition in definitions(ORIGINAL) if definition.kind == 'func')
        text = ORIGINAL[function.start:function.end]
        text = text.replace('// Скобки в строке и комментарии не завершают функцию: }', '// corrupted \ufffd')
        (self.source/'items/it_potions.d').write_text(text, encoding='utf-8')
        self.assertEqual((self.prepare()/'ITEMS/IT_Potions.D').read_bytes(), ORIGINAL.encode('cp1251'))

    def test_new_constant_is_inserted_before_the_modified_instance_using_it(self):
        original = parse_items(self.original, 'game')[0]
        block = original.text.replace('value = 25;', 'value = NewValue;')
        (self.source/'items/it_potions.d').write_bytes(
            ('const int NewValue = 70;\n' + block + ';').encode('cp1251'))
        text = load_text(self.prepare()/'ITEMS/IT_Potions.D')[0]
        self.assertLess(text.index('const int NewValue'), text.index('INSTANCE ItPo_Health_01'))
        self.assertIn('value = NewValue;', text)


if __name__ == '__main__':
    unittest.main()
