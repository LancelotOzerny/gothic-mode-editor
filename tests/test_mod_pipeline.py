import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.project_tools import ProjectTools, ToolResult
from gothic_editor.core.build_pipeline import BuildPipeline
from gothic_editor.core.mod_config import ModConfiguration
from gothic_editor.core.mod_package import DAT_PATH, ModPackageService, generate_ini, read_ini, validate_build
from gothic_editor.core.mod_archive import read_mod, write_mod
from gothic_editor.core.mod_launch import ModLauncherService
from gothic_editor.core.item_assets import ItemAssetManager
from gothic_editor.core.model_export import geometry_3ds
from gothic_editor.core.settings import SettingsStore


class ModPipelineTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='mod pipeline ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.game=self.root/'game'
        self.content=self.game/'_work/Data/Scripts/Content'
        (self.content/'Items').mkdir(parents=True)
        (self.content/'Gothic.src').write_bytes(b'Items\\IT_*.d\n')
        (self.content/'Items/IT_Test.d').write_bytes(b'const int ORIGINAL = 1;')
        (self.game/'System').mkdir()
        (self.game/'System/GothicStarter.exe').write_bytes(b'test starter')
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Reforged')
        self.compiler=self.root/'compiler.exe'
        self.compiler.write_bytes(b'compiler')

    def tools(self):
        return ProjectTools(self.repo.root,self.game,str(self.compiler))

    def compile_process(self,command,**kwargs):
        dat=Path(command[command.index('--output-dat')+1])
        dat.write_bytes(b'fresh DAT')
        return subprocess.CompletedProcess(command,0)

    def compile(self,tools=None):
        tools=tools or self.tools()
        with patch('gothic_editor.core.compiler_runner.subprocess.run',side_effect=self.compile_process):
            return tools.compile()

    def test_compile_publishes_mod_ini_assets_and_removes_temporary_dat(self):
        item=self.repo.create_item('potions')
        source=self.root/'source.3ds'
        source.write_bytes(geometry_3ds([(0.,0.,0.),(1.,0.,0.),(0.,1.,0.)],[(0,1,2)]))
        ItemAssetManager(self.repo.root).import_model(item,source)
        texture=self.root/'Custom.TGA'
        texture.write_bytes(b'texture')
        ItemAssetManager(self.repo.root).import_textures(item,[texture])
        result=self.compile()
        self.assertEqual(result.output,self.repo.root/'dist/Reforged.mod')
        files=read_mod(result.output)
        self.assertEqual(files[DAT_PATH],b'fresh DAT')
        self.assertEqual(files['_work/data/meshes/model_itpo_potion1.3ds'],source.read_bytes())
        self.assertEqual(files['_work/data/textures/custom.tga'],b'texture')
        self.assertFalse((self.repo.root/'dist/Gothic.dat').exists())
        self.assertFalse((self.repo.root/'build').exists())
        validate_build(result.output,result.output.with_suffix('.ini'),self.tools().config)
        diagnostic=json.loads((self.repo.root/'logs/compiler.diagnostics.json').read_text('utf-8'))
        self.assertFalse(Path(diagnostic['cwd']).exists())

    def test_debug_dat_and_custom_ini_parameters_are_preserved(self):
        self.repo.save_project_settings({'project.mod.keep_dat':True,'project.mod.output_name':'Custom.mod'})
        self.compile()
        ini=self.repo.root/'dist/Custom.ini'
        with ini.open('ab') as stream:stream.write(b'\r\n; User comment\r\n[OPTIONS]\r\nforce_Parameters=-zWindow\r\n[CUSTOM]\r\nKeep=Yes\r\n')
        self.compile()
        self.assertEqual((self.repo.root/'dist/Gothic.dat').read_bytes(),b'fresh DAT')
        parser=read_ini(ini)
        self.assertEqual(parser['CUSTOM']['Keep'],'Yes')
        self.assertEqual(parser['OPTIONS']['force_Parameters'],'-zWindow')
        self.assertIn(b'; User comment',ini.read_bytes())
        self.assertEqual(ini.read_text('cp1251').count('[FILES]'),1)
        self.repo.save_project_settings({'project.mod.keep_dat':False})
        self.compile()
        self.assertFalse((self.repo.root/'dist/Gothic.dat').exists())

    def test_compile_and_package_errors_preserve_previous_dist_and_skip_later_stages(self):
        self.compile()
        before={p.name:p.read_bytes() for p in (self.repo.root/'dist').iterdir()}
        tools=self.tools()
        with patch('gothic_editor.core.compiler_runner.subprocess.run',return_value=subprocess.CompletedProcess([],1)), \
                patch.object(tools,'synchronize') as sync,patch.object(tools,'launch') as launch:
            with self.assertRaises(ValueError):tools.build_and_run()
        sync.assert_not_called()
        launch.assert_not_called()
        with patch('gothic_editor.core.compiler_runner.subprocess.run',side_effect=self.compile_process), \
                patch.object(ModPackageService,'package',side_effect=OSError('packer failed')):
            with self.assertRaises(OSError):tools.compile()
        self.assertEqual({p.name:p.read_bytes() for p in (self.repo.root/'dist').iterdir()},before)
        self.assertIn('packer failed',(self.repo.root/'logs/compile.log').read_text('utf-8'))

    def test_stale_dat_in_valid_mod_is_rejected_before_publishing(self):
        self.compile()
        old=(self.repo.root/'dist/Reforged.mod').read_bytes()
        def stale(service,staging,compiled,files,log):
            output=staging/service.config.filename
            write_mod(output,{DAT_PATH:b'outdated DAT'})
            return output
        with patch.object(ModPackageService,'package',stale), \
                patch('gothic_editor.core.compiler_runner.subprocess.run',side_effect=self.compile_process):
            with self.assertRaisesRegex(ValueError,'устаревший'):self.tools().compile()
        self.assertEqual((self.repo.root/'dist/Reforged.mod').read_bytes(),old)

    def test_install_coexists_with_other_mods_and_refuses_foreign_files(self):
        self.compile()
        other=self.game/'Data/ModVDF/Other.mod'
        other.parent.mkdir(parents=True)
        other.write_bytes(b'other mod')
        original=self.content/'Items/IT_Test.d'
        original_bytes=original.read_bytes()
        tools=self.tools()
        tools.synchronize()
        self.assertEqual(other.read_bytes(),b'other mod')
        self.assertEqual(original.read_bytes(),original_bytes)
        receipt=json.loads((self.repo.root/'project.json').read_text('utf-8'))['mod_installations']
        self.assertTrue(receipt)
        second=ProjectRepository()
        second.create(self.root/'second','Reforged')
        shutil.copytree(self.repo.root/'dist',second.root/'dist')
        with self.assertRaisesRegex(ValueError,'не принадлежит'):
            ProjectTools(second.root,self.game,str(self.compiler)).synchronize()
        self.assertEqual((self.game/'Data/ModVDF/Reforged.mod').read_bytes(),(self.repo.root/'dist/Reforged.mod').read_bytes())
        installed_ini=self.game/'System/Reforged.ini'
        installed_ini.write_bytes(installed_ini.read_bytes()+b'\n; edited outside\n')
        with self.assertRaisesRegex(ValueError,'изменён извне'):tools.synchronize()

    def test_launch_is_independent_and_uses_selected_ini_or_manual_fallback(self):
        self.compile()
        tools=self.tools()
        tools.synchronize()
        shutil.rmtree(self.repo.root/'dist')
        shutil.rmtree(self.repo.root/'Scripts')
        tools=self.tools()  # Launch needs no compiler sources or dist.
        with patch('gothic_editor.core.mod_launch.starter_supports_direct',return_value=True), \
                patch('gothic_editor.core.mod_launch.subprocess.Popen',return_value=Mock(pid=42)) as spawn:
            result=tools.launch()
        self.assertFalse(result.manual)
        command=spawn.call_args.args[0]
        self.assertEqual(command[1:],['-start','-game:Reforged.ini'])
        self.assertEqual(spawn.call_args.kwargs['cwd'],self.game/'System')
        with patch('gothic_editor.core.mod_launch.starter_supports_direct',return_value=False), \
                patch('gothic_editor.core.mod_launch.subprocess.Popen',return_value=Mock(pid=43)) as spawn:
            self.assertTrue(tools.launch().manual)
        self.assertEqual(len(spawn.call_args.args[0]),1)
        self.assertIn('Reforged.ini',(self.repo.root/'logs/launch.log').read_text('utf-8'))

    def test_pipeline_stops_after_sync_error_and_succeeds_in_order(self):
        tools=Mock()
        order=[]
        tools.compile.side_effect=lambda report:order.append('compile') or ToolResult(Path('mod'))
        tools.synchronize.side_effect=ValueError('conflict')
        with self.assertRaisesRegex(ValueError,'conflict'):BuildPipeline(tools).run()
        tools.launch.assert_not_called()
        tools.synchronize.side_effect=lambda report:order.append('sync') or ToolResult(Path('mod'),operation='sync')
        tools.launch.side_effect=lambda report:order.append('launch') or ToolResult(Path('ini'),operation='launch')
        order.clear()
        self.assertEqual(BuildPipeline(tools).run().operation,'launch')
        self.assertEqual(order,['compile','sync','launch'])

    def test_invalid_build_ini_or_missing_starter_cannot_install_or_launch(self):
        self.compile()
        ini=self.repo.root/'dist/Reforged.ini'
        ini.write_text('[FILES]\nVDF=Other.mod\nGame=Content\\Gothic\n',encoding='cp1251')
        with self.assertRaises(ValueError):self.tools().synchronize()
        self.assertFalse((self.game/'Data/ModVDF/Reforged.mod').exists())
        ini.unlink()
        self.compile()
        tools=self.tools()
        tools.synchronize()
        (self.game/'System/GothicStarter.exe').unlink()
        with self.assertRaisesRegex(ValueError,'Не найден GothicStarter'):tools.launch()

    def test_external_packer_command_and_exact_byte_verification(self):
        tool=self.root/'GothicVDFS.exe'
        tool.write_bytes(b'packer')
        config=ModConfiguration('External','External.mod',packer_path=str(tool))
        service=ModPackageService(self.repo.root,self.game,config)
        staging=self.root/'staging'
        staging.mkdir()
        compiled=staging/'Gothic.dat'
        compiled.write_bytes(b'current')
        def pack(command,**kwargs):
            self.assertEqual(command[1],'/B')
            self.assertTrue(Path(command[2]).is_absolute())
            self.assertIn('BaseDir=volume',Path(command[2]).read_text('cp1251'))
            write_mod(staging/'External.mod',{DAT_PATH:b'current'})
            return subprocess.CompletedProcess(command,0,b'',b'')
        with patch('gothic_editor.core.mod_package.subprocess.run',side_effect=pack):
            result=service.package(staging,compiled,{},lambda _:None)
        self.assertEqual(read_mod(result)[DAT_PATH],b'current')

    def test_project_game_paths_are_separate_and_do_not_enter_global_settings(self):
        self.repo.save_project_settings({'resources.gothic.game_path':str(self.game),'project.mod.name':'First'})
        other=self.root/'other-game'
        other.mkdir()
        second=ProjectRepository()
        second.create(self.root/'second','Second')
        second.save_project_settings({'resources.gothic.game_path':str(other)})
        self.repo.open(self.repo.root)
        second.open(second.root)
        self.assertEqual(self.repo.game,self.game)
        self.assertEqual(second.game,other)
        store=SettingsStore(self.root/'global.json')
        from gothic_editor.core.settings import EditorSettings
        store.save(EditorSettings({'resources.gothic.game_path':str(self.game)}))
        self.assertNotIn('resources.gothic.game_path',json.loads(store.path.read_text('utf-8')))
