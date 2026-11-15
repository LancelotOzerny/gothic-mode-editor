"""NPC-only appearance overrides, native previews and world editor mode."""
import json
import os
from pathlib import Path
import struct
import tempfile
from time import monotonic
import unittest
from unittest.mock import patch

from gothic_editor.core.npcs import NpcCatalog,NpcStore,apply_npc_overrides
from gothic_editor.core.npc_models import NpcModelIndex,read_npc_mesh,load_npc_preview,hierarchy
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.build_assets import BuildAssetService
from gothic_editor.core.scripts import load_text
from test_models import mrm_bytes


def chunk(kind,data=b''):return struct.pack('<HI',kind,len(data))+data


def mdm():
    return (chunk(0xD000,struct.pack('<I',0x04030506))+chunk(0xD030,struct.pack('<IH',123,1))+
            chunk(0xE100,struct.pack('<I',4))+mrm_bytes()+chunk(0xE110)+chunk(0xD040))


SOURCE='''prototype Npc_Default(C_NPC) { name="Base"; };
func void SetVisuals() {
 Mdl_SetVisual(self,"Humans.MDS");
 Mdl_SetVisualBody(self,"Body",2,0,"",3,0,-1);
};
instance NPC_A(Npc_Default) {name="A"; SetVisuals(); custom=VALUE+7;};
instance NPC_B(Npc_Default) {name="B"; B_SetNpcVisual(self,MALE,"Head",FACE,2,-1);};
func void Other() { var int x; x=1; };
const int FACE=12;
const int MALE=0;
'''


class NpcFixture:
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='npc appearance ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Test')
        self.game=self.root/'game'
        self.content=self.game/'_work/Data/Scripts/Content'
        self.content.mkdir(parents=True)
        self.script=self.content/'NPC.d'
        self.script.write_text(SOURCE,encoding='cp1251')
        self.body=self.game/'_work/Data/Anims/_compiled/Body.MDM'
        self.body.parent.mkdir(parents=True)
        self.body.write_bytes(mdm())
        self.repo.game=self.game
        self.repo.refresh()
        self.store=NpcStore(self.repo.root)


class NpcTests(NpcFixture,unittest.TestCase):
    def test_catalog_inherits_names_and_follows_visual_helpers(self):
        catalog=NpcCatalog(self.repo.root,self.game)
        npcs=catalog.load()
        self.assertEqual([npc.instance for npc in npcs],['NPC_A','NPC_B'])
        self.assertEqual(npcs[0].body,'Body')
        self.assertEqual(npcs[0].visual,'Humans.MDS')
        self.assertEqual(npcs[1].body,'Hum_Body_Naked0')
        self.assertEqual(catalog.integer(npcs[1].body_args[4]),12)

    def test_save_reload_reset_preserve_originals_and_only_patch_target_instance(self):
        original=self.script.read_bytes()
        self.store.save('NPC_A',{'name':'Новое имя','body':'NewBody','head':''})
        npc=next(npc for npc in NpcCatalog(self.repo.root,self.game).load() if npc.instance=='NPC_A')
        self.assertEqual(npc.title,'Новое имя')
        self.assertEqual(npc.body,'NewBody')
        stage=self.root/'stage'
        stage.mkdir()
        staged=stage/'NPC.d'
        staged.write_bytes(original)
        apply_npc_overrides(self.repo.root,stage)
        text,_=load_text(staged)
        self.assertIn('name[0] = "Новое имя";',text)
        self.assertIn('Mdl_SetVisualBody(self, "NewBody", 2, 0, "", 3, 0, -1);',text)
        self.assertIn('custom=VALUE+7;',text)
        self.assertIn('instance NPC_B(Npc_Default) {name="B";',text)
        self.assertIn('func void Other()',text)
        self.assertEqual(self.script.read_bytes(),original)
        self.store.save('NPC_A',{})
        self.assertFalse(self.store.read())
        self.assertEqual(next(npc for npc in NpcCatalog(self.repo.root,self.game).load() if npc.instance=='NPC_A').body,'Body')

    def test_missing_npc_and_invalid_metadata_fail_without_touching_scripts(self):
        for value in ({'name':''},{'body':'../unsafe'},{'armor':'Bad();'},{'unknown':'1'}):
            with self.assertRaises(ValueError):self.store.save('NPC_A',value)
        self.store.save('MISSING',{'name':'Test'})
        with self.assertRaisesRegex(ValueError,'missing'):apply_npc_overrides(self.repo.root,self.content)
        self.assertEqual(self.script.read_text('cp1251'),SOURCE)

    def test_native_body_and_imported_models_preview_and_package(self):
        catalog=NpcCatalog(self.repo.root,self.game)
        npc=catalog.load()[0]
        index=NpcModelIndex(self.repo)
        preview=load_npc_preview(npc,index,catalog)
        self.assertTrue(preview.mesh.faces)
        self.assertEqual(read_npc_mesh(mdm()).faces,preview.mesh.faces)
        model=index.import_model(self.body,'body')
        path=self.repo.root/'Assets/NPC/Models'/(model+'.mdm')
        self.assertEqual(path.read_bytes(),self.body.read_bytes())
        files=BuildAssetService(self.repo.root).collect()
        self.assertEqual(files['_work/data/Anims/_compiled/'+path.name],self.body.read_bytes())
        self.assertFalse(any('overrides.json' in name for name in files))
        for invalid in (b'',b'bad',chunk(0xD030,b'x')):
            with self.assertRaises(ValueError):read_npc_mesh(invalid)

    def test_hierarchy_rest_translation_and_parent_transforms(self):
        identity=(1.,0.,0.,1., 0.,1.,0.,2., 0.,0.,1.,3., 0.,0.,0.,1.)
        data=struct.pack('<IH',3,1)+b'BIP01 HEAD\n'+struct.pack('<h16f',-1,*identity)
        data+=bytes(48)+struct.pack('<3f',0,100,0)+bytes(4)
        matrix=hierarchy(chunk(0xD100,data))['BIP01 HEAD']
        self.assertEqual((matrix[3],matrix[7],matrix[11]),(1,102,3))


class NpcUITests(NpcFixture,unittest.TestCase):
    def test_top_level_mode_npc_name_flush_and_return_to_items(self):
        from gothic_editor.app import EditorApp
        from gothic_editor.core.settings import SettingsStore
        with patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(self.root/'settings.json')):
            app=EditorApp()
        try:
            app.withdraw()
            app.repo=self.repo
            app.show_project()
            app.deiconify()
            app.update()
            self.assertEqual([value for _,value in app.mode.options],['items','world'])
            self.assertFalse(hasattr(app,'_browser_buttons'))
            app.mode.set_expression('world')
            app.mode.event_generate('<<ComboboxSelected>>')
            self.assertEqual(app._resource_browser,'world')
            npc=next(value for value in app.npcs.items if value.instance=='NPC_A')
            app.npcs.select(npc)
            deadline=monotonic()+5
            while app._model_future is not None and monotonic()<deadline:app.update()
            self.assertTrue(app.viewer.vertices)
            entry=app.npc_properties.fields['name']
            entry.delete(0,'end');entry.insert(0,'Новое имя')
            self.assertIsNotNone(app.npcs.pending)
            app._switch_resource_browser('items')
            self.assertEqual(self.store.read()['npc_a']['name'],'Новое имя')
            self.assertIsNone(app.npcs.current)
            app._switch_resource_browser('world')
            app.npcs.select(npc)
            self.assertEqual(app.npc_properties.fields['name'].get(),'Новое имя')
            app.npcs.reset()
            self.assertEqual(app.npc_properties.fields['name'].get(),'A')
        finally:app.destroy()


class NpcGameTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('GOTHIC_TEST_GAME') and os.environ.get('GOTHIC_TEST_COMPILER'),'Optional actual game/GDC')
    def test_actual_human_monster_previews_and_compilation(self):
        from gothic_editor.core.project_tools import ProjectTools
        from gothic_editor.core.mod_package import ModPackageService
        from gothic_editor.core.mod_archive import read_mod
        with tempfile.TemporaryDirectory(prefix='npc game ') as temporary:
            root=Path(temporary)
            repo=ProjectRepository();repo.create(root/'project','NpcTest')
            repo.game=Path(os.environ['GOTHIC_TEST_GAME']);repo.refresh()
            catalog=NpcCatalog(repo.root,repo.game);npcs=catalog.load();index=NpcModelIndex(repo)
            for code in ('VLK_439_Vatras','Razor','PC_Hero'):
                npc=next(value for value in npcs if value.instance==code)
                preview=load_npc_preview(npc,index,catalog,True)
                self.assertTrue(preview.mesh.faces)
                self.assertFalse(preview.missing)
            npc=next(value for value in npcs if value.instance=='VLK_439_Vatras')
            original=npc.path.read_bytes()
            native=root/'Body.MDM'
            native.write_bytes(index.find('Hum_Body_Naked0',('.mdm',)).read_bytes())
            imported=index.import_model(native,'body')
            NpcStore(repo.root).save(npc.instance,{'name':'Проверка NPC','body':imported,'armor':'-1','head':'Hum_Head_FatBald'})
            with patch.object(ModPackageService,'packer',return_value=None):
                result=ProjectTools(repo.root,repo.game,os.environ['GOTHIC_TEST_COMPILER']).compile()
            packed=read_mod(result.output)
            self.assertTrue(packed['_work/data/scripts/_compiled/gothic.dat'])
            self.assertEqual(packed['_work/data/anims/_compiled/'+imported.casefold()+'.mdm'],native.read_bytes())
            self.assertEqual(npc.path.read_bytes(),original)
