import tempfile
import unittest
from pathlib import Path

from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.scripts import parse_items


class PotionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Potions')

    def test_creation_defaults_numbering_and_reuse_consider_game_ids(self):
        source=self.root/'game/_work/Data/Scripts/Content/Items/IT_Test.d'
        source.parent.mkdir(parents=True)
        source.write_text('INSTANCE ITPO_POTION1(C_Item) { name="Original"; };',encoding='utf-8')
        self.repo.set_game_path(str(self.root/'game'))
        item=self.repo.create_item('potions')
        self.assertEqual(item.instance,'ItPo_Potion2')
        self.assertEqual(item.fields,{'name':'"Новое зелье"','description':'"Новое зелье"',
            'flags':'ITEM_MULTI','value':'100','mainflag':'ITEM_KAT_POTIONS',
            'visual':'"ItPo_Perm_Health.3ds"','material':'MAT_GLAS','scemename':'"POTIONFAST"',
            'text[5]':'NAME_Value','count[5]':'value'})
        other=self.repo.create_item('potions','Custom name')
        self.assertEqual(other.instance,'ItPo_Potion3')
        self.assertEqual(other.fields['name'],other.fields['description'])
        self.assertEqual(other.fields['name'],'"Custom name"')
        self.repo.delete(item)
        self.assertEqual(self.repo.create_item('potions').instance,'ItPo_Potion2')

    def test_existing_source_helpers_and_components_survive_reopen_and_build(self):
        content=self.root/'game/_work/Data/Scripts/Content'
        (content/'Items').mkdir(parents=True)
        source=content/'Items/IT_Test.d'
        original=('const int PRICE = 100;\n'
            'func void Drink() { var int bonus; bonus = PRICE; };\n'
            'INSTANCE ItPo_Original(C_Item) {\n'
            '    name = NAME_Trank;\n'
            '    description = "Original";\n'
            '    mainflag = ITEM_KAT_POTIONS;\n'
            '    value = PRICE;\n'
            '    custom = PRICE /* keep comment */ + 2;\n'
            '    on_state[0] = Drink;\n'
            '    TEXT[0] = "Custom";\n'
            '};\n'
            'INSTANCE ItPo_Sibling(C_Item) { name="Sibling"; };\n')
        source.write_text(original,encoding='cp1251')
        (content/'Gothic.src').write_text('Items\\IT_*.d\n',encoding='cp1251')
        self.repo.set_game_path(str(self.root/'game'))
        item=self.repo.copy_to_project(next(i for i in self.repo.game_items if i.instance=='ItPo_Original'))
        self.assertEqual(item.text,parse_items(source,'game')[0].text)
        changed=self.repo.edit(item,{'description':'"Changed"','value':'PRICE * 2'})
        self.repo.open(self.repo.root)
        reopened=next(i for i in self.repo.project_items if i.instance=='ItPo_Original')
        self.assertEqual(reopened.text,changed.text)
        expected=item.text.replace('description = "Original";','description = "Changed";').replace(
            'value = PRICE;','value = PRICE * 2;')
        self.assertEqual(reopened.text,expected)
        self.assertNotIn('flags',reopened.fields)
        self.assertNotIn('visual',reopened.fields)
        self.assertEqual(reopened.path,self.repo.root/'Assets/Items/Potions/ItPo_Original.json')
        self.assertEqual(sorted(p.name for p in reopened.path.parent.iterdir()),['ItPo_Original.json'])
        self.repo.edit(reopened,{'value':'PRICE + 7'})
        with tempfile.TemporaryDirectory() as temporary:
            staged,_,_=ProjectTools(self.repo.root,self.repo.game)._prepare(Path(temporary),lambda _:None)
            self.assertEqual((staged/'Items/IT_Test.d').read_text('utf-8-sig'),
                original.replace('description = "Original";','description = "Changed";').replace(
                    'value = PRICE;','value = PRICE + 7;'))
        self.assertEqual(source.read_text('cp1251'),original)
