"""XLSX exchange tests; only temporary projects and synthetic schemas are used."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile,ZIP_DEFLATED
from xml.etree import ElementTree as ET

from gothic_editor.core.xlsx import write_table,read_table,NS,REL
from gothic_editor.core.item_spreadsheet import export_items,ItemSpreadsheetService,CODE,CATEGORY
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.properties_schema import PropertiesSchema,PropertySection,PropertyField
from gothic_editor.core.scripts import parse_items


def synthetic_schema(category):
    return PropertiesSchema((PropertySection('general','General',(
        PropertyField('mainflag','Category',default='ITEM_KAT_POTIONS' if category=='potions' else 'ITEM_KAT_RUNE'),
        PropertyField('name','Name',default='"Default"'),
        PropertyField('value','Value',field_type='expression',default='0'),
    )),))


class TemporarySpreadsheetCase(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='xlsx exchange ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def rewrite_zip(self,path,changes):
        with ZipFile(path) as archive:data={name:archive.read(name) for name in archive.namelist()}
        data.update(changes)
        with ZipFile(path,'w',ZIP_DEFLATED) as archive:
            for name,value in data.items():archive.writestr(name,value)


class SpreadsheetTests(TemporarySpreadsheetCase):
    def test_standard_parts_inline_strings_sparse_cells_and_literal_formula(self):
        path=self.root/'русское имя.xlsx'
        rows=[['Код','Название','value'],['ItPo_Test','"Привет & <мир>"','2'],
              ['ItPo_Next','','=DO_NOT_EXECUTE()'],['ItPo_Last','_x0041_\r\nline','0']]
        progress=[]
        write_table(path,rows,lambda *message:progress.append(message))
        self.assertEqual(read_table(path),rows)
        with ZipFile(path) as archive:
            self.assertIn('xl/workbook.xml',archive.namelist())
            self.assertIn('Предметы',archive.read('xl/workbook.xml').decode())
            sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            self.assertFalse(list(sheet.iter('{'+NS+'}f')))
        self.assertEqual(progress[-1][0],len(rows))

    def test_excel_shared_strings_numbers_and_relationships(self):
        path=self.root/'excel.xlsx'
        write_table(path,[['placeholder']])
        self.rewrite_zip(path,{
            'xl/_rels/workbook.xml.rels':f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/worksheet" Target="/xl/worksheets/custom.xml"/><Relationship Id="strings" Type="{REL}/sharedStrings" Target="strings.xml"/></Relationships>',
            'xl/strings.xml':f'<sst xmlns="{NS}"><si><t>Код</t></si><si><r><t>ItPo_</t></r><r><t>Test</t></r></si></sst>',
            'xl/worksheets/custom.xml':f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>value</t></is></c></row><row r="3"><c r="A3" t="s"><v>1</v></c><c r="C3"><v>42</v></c></row></sheetData></worksheet>',
        })
        self.assertEqual(read_table(path),[['Код','','value'],[],['ItPo_Test','','42']])

    def test_failed_export_preserves_destination_and_formulas_are_rejected_on_import(self):
        path=self.root/'existing.xlsx'
        path.write_bytes(b'previous')
        with self.assertRaises(ValueError):write_table(path,[['bad\x00text']])
        self.assertEqual(path.read_bytes(),b'previous')
        self.assertEqual(list(self.root.glob('.xlsx-*')),[])
        write_table(path,[['x']])
        self.rewrite_zip(path,{'xl/worksheets/sheet1.xml':f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'})
        with self.assertRaisesRegex(ValueError,'формулу'):read_table(path)


class ItemExchangeTests(TemporarySpreadsheetCase):
    def setUp(self):
        super().setUp()
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Test')
        patcher=patch('gothic_editor.core.item_spreadsheet.schema_for',side_effect=synthetic_schema)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service=ItemSpreadsheetService(self.repo)

    def item(self,code='ItPo_Existing'):
        return self.repo.create_item_from_fields(code,{'name':'"Before"','mainflag':'ITEM_KAT_POTIONS',
            'value':'3','unknown':'BASE + 2','text[5]':'NAME_Value','count[5]':'value'})

    def table(self,rows,headers=None):
        path=self.root/'items.xlsx'
        write_table(path,[headers or [CODE,CATEGORY,'name','value']]+rows)
        return path

    def test_export_round_trip_keeps_arrays_expressions_metadata_and_owned_resources(self):
        item=self.item()
        item=self.repo.edit(item,{},metadata={'label':'Подпись'})
        resources=item.path.parent/'assets'
        resources.mkdir()
        (resources/'texture.tga').write_bytes(b'keep texture')
        (item.path.parent/'functions.d').write_text('func void KeepHelper() {};',encoding='utf-8')
        original=item.path.read_bytes()
        path=self.root/'export.xlsx'
        self.assertEqual(export_items(self.repo.project_items,path),1)
        rows=read_table(path)
        self.assertEqual(rows[0][:4],[CODE,CATEGORY,'name','mainflag'])
        self.assertIn('text[5]',rows[0])
        result=self.service.import_file(path,'replace')
        self.assertEqual((result.created,result.updated,result.skipped),(0,1,0))
        self.assertEqual(item.path.read_bytes(),original)
        self.assertEqual((resources/'texture.tga').read_bytes(),b'keep texture')
        self.assertIn('KeepHelper',(item.path.parent/'functions.d').read_text('utf-8'))

    def test_three_import_modes_match_ids_case_insensitively(self):
        for mode,created,updated in [('replace',1,1),('missing',1,0),('update',0,1)]:
            with self.subTest(mode=mode):
                repo=ProjectRepository()
                repo.create(self.root/mode,'Mode')
                repo.create_item_from_fields('ItPo_Existing',{'name':'"Before"','mainflag':'ITEM_KAT_POTIONS'})
                path=self.table([['itpo_existing','potions','"After"','8'],['ItPo_New','potions','"New"','5']])
                result=ItemSpreadsheetService(repo).import_file(path,mode)
                self.assertEqual((result.created,result.updated),(created,updated))
                existing=next(item for item in repo.items if item.instance=='ItPo_Existing')
                self.assertEqual(existing.fields['name'],'"After"' if updated else '"Before"')
                self.assertEqual(len(repo.project_items),1+created)

    def test_complete_validation_precedes_writes_and_duplicate_ids_fail(self):
        item=self.item()
        original=item.path.read_bytes()
        for rows in (
            [['ItPo_Existing','potions','"Good"','1'],['ItPo_Invalid','potions','"New"','2 minutes']],
            [['ItPo_Existing','potions','"Good"','1'],['ITPO_EXISTING','potions','"Again"','2']],
            [['../escape','potions','"Invalid"','1']],
        ):
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                self.service.import_file(self.table(rows),'replace')
            self.assertEqual(item.path.read_bytes(),original)
            self.assertEqual(len(self.repo.project_items),1)

    def test_io_failure_rolls_back_updated_items_and_removes_created_components(self):
        item=self.item()
        before=item.path.read_bytes()
        path=self.table([['ItPo_Existing','potions','"Changed"','7'],['ItPo_New','potions','"New"','2']])
        original=self.repo.create_item_from_fields
        def fail(*args,**kwargs):
            original(*args,**kwargs)
            raise OSError('Simulated disk failure')
        with patch.object(self.repo,'create_item_from_fields',side_effect=fail),self.assertRaises(OSError):
            self.service.import_file(path,'replace')
        self.assertEqual(item.path.read_bytes(),before)
        self.assertFalse(self.repo.components.folder('ItPo_New').exists())
        self.assertEqual(len(self.repo.project_items),1)
        self.assertTrue(list((self.repo.root/'backups').glob('xlsx-import-*')))

    def test_scroll_updates_keep_neighbor_instances_and_functions_in_shared_script(self):
        folder=self.repo._project_content()/'Items'
        path=folder/'scrolls.d'
        path.write_text('func void Helper() {};\nINSTANCE ItSc_A(C_Item) {mainflag=ITEM_KAT_RUNE; name="A";};\n'
            'INSTANCE ItSc_B(C_Item) {mainflag=ITEM_KAT_RUNE; name="B";};',encoding='cp1251')
        self.repo.refresh()
        table=self.table([['ItSc_A','scrolls','"Changed A"','1'],['ItSc_B','scrolls','"Changed B"','2'],
                          ['ItSc_New','scrolls','"New scroll"','3']])
        result=self.service.import_file(table,'replace')
        self.assertEqual((result.created,result.updated),(1,2))
        self.assertEqual([item.fields['name'] for item in parse_items(path,'project')],['"Changed A"','"Changed B"'])
        self.assertIn('func void Helper()',path.read_text('cp1251'))

    def test_readonly_categories_are_skipped_and_blank_cells_preserve_fields(self):
        item=self.item()
        path=self.table([['ItPo_Existing','potions','',''],['ItMw_Weapon','onehand','"Weapon"','1']])
        result=self.service.import_file(path,'replace')
        self.assertEqual(result.readonly,1)
        self.assertEqual(self.repo.items[0].fields,item.fields)

    def test_game_item_update_creates_project_override_without_touching_original(self):
        content=self.root/'game/_work/data/Scripts/Content/Items'
        content.mkdir(parents=True)
        original=content/'IT_Test.d'
        code='func void OnUse() {};\nINSTANCE ItPo_Game(C_Item) {mainflag=ITEM_KAT_POTIONS; name="Game"; on_state[0]=OnUse; custom=BASE+2;};'
        original.write_text(code,encoding='cp1251')
        self.repo.game=self.root/'game'
        self.repo.refresh()
        table=self.table([['itpo_game','potions','"Project"','9']])
        result=self.service.import_file(table,'update')
        self.assertEqual(result.updated,1)
        self.assertEqual(original.read_text('cp1251'),code)
        item=self.repo.project_items[0]
        self.assertTrue(self.repo.components.owns(item.path))
        self.assertEqual(item.fields['custom'],'BASE+2')
        self.assertEqual(item.fields['on_state[0]'],'OnUse')
        self.assertEqual(item.fields['name'],'"Project"')
