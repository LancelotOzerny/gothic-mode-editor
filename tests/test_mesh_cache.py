"""Cache invalidation uses only temporary games; no working item schemas."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gothic_editor.core.mesh_cache import MeshCache
from gothic_editor.core.mod_archive import write_mod
from gothic_editor.core.mod_config import ModConfiguration
from gothic_editor.core.mod_install import ModInstallerService
from gothic_editor.core.mod_launch import ModLauncherService
from gothic_editor.core.mod_package import DAT_PATH, generate_ini


class MeshCacheTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='mesh cache ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.project=self.root/'project'
        self.game=self.root/'game'
        (self.project/'dist').mkdir(parents=True)
        (self.project/'project.json').write_text(json.dumps({'name':'CacheTest'}))
        self.config=ModConfiguration.load(self.project)
        self.folder=self.game/'_work/DATA/meshes/_COMPILED'
        self.folder.mkdir(parents=True)
        self.cache=self.folder/'SKILL_POTION.MRM'
        self.static=self.folder/'Skill_Potion.MSH'
        self.cache.write_bytes(b'old small model')
        self.static.write_bytes(b'old static model')
        (self.folder/'Other.mrm').write_bytes(b'another mod')
        (self.folder/'skill_potion.mdl').write_bytes(b'not static geometry')
        self.files={DAT_PATH:b'dat','_work/data/Meshes/skill_potion.3ds':b'new larger model'}
        self.archive=self.project/'dist'/self.config.filename
        self.ini=self.project/'dist'/self.config.ini_name
        write_mod(self.archive,self.files)
        generate_ini(self.ini,self.config)
        (self.game/'System').mkdir()
        (self.game/'System/GothicStarter.exe').write_bytes(b'starter')
        self.installer=ModInstallerService(self.project,self.game,self.config)

    def test_matching_cache_removed_with_backups_and_other_files_preserved(self):
        log=[]
        MeshCache(self.project,self.game).invalidate(self.files,log.append)
        self.assertFalse(self.cache.exists())
        self.assertFalse(self.static.exists())
        self.assertEqual((self.folder/'Other.mrm').read_bytes(),b'another mod')
        self.assertEqual((self.folder/'skill_potion.mdl').read_bytes(),b'not static geometry')
        backups=list((self.project/'backups').glob('mesh-cache-*'))
        self.assertEqual(len(backups),1)
        backup=backups[0]/self.cache.relative_to(self.game)
        self.assertEqual(backup.read_bytes(),b'old small model')
        self.assertEqual(len(log),2)
        MeshCache(self.project,self.game).invalidate(self.files,log.append)
        self.assertEqual(len(list((self.project/'backups').glob('mesh-cache-*'))),1)

    def test_no_cleanup_without_source_models_or_directory(self):
        service=MeshCache(self.project,self.game)
        self.assertFalse(service.plan({DAT_PATH:b'dat','_work/data/Meshes/_compiled/skill_potion.mrm':b'compiled'}))
        self.folder.rename(self.folder.with_name('unused'))
        self.assertFalse(service.plan(self.files))

    def test_installer_cleans_cache_even_when_mod_is_unchanged(self):
        result=self.installer.install()
        self.assertEqual(result.files,2)
        self.assertFalse(self.cache.exists())
        self.cache.write_bytes(b'recompiled cache')
        result=self.installer.install()
        self.assertEqual(result.files,0)
        self.assertFalse(self.cache.exists())
        self.assertIn('SKILL_POTION.MRM',(self.project/'logs/sync.log').read_text('utf-8'))

    def test_install_failure_restores_cache_receipt_and_installed_mod(self):
        self.installer.install()
        self.cache.write_bytes(b'keep cache on failure')
        installed=self.game/'Data/ModVDF'/self.config.filename
        old_mod=installed.read_bytes()
        old_config=(self.project/'project.json').read_bytes()
        self.files[DAT_PATH]=b'new dat'
        write_mod(self.archive,self.files)
        with patch('gothic_editor.core.mod_install.validate_build',
                   side_effect=[self.files,ValueError('verification failed')]):
            with self.assertRaisesRegex(ValueError,'verification failed'):self.installer.install()
        self.assertEqual(self.cache.read_bytes(),b'keep cache on failure')
        self.assertEqual(installed.read_bytes(),old_mod)
        self.assertEqual((self.project/'project.json').read_bytes(),old_config)

    def test_locked_cache_prevents_installation_and_restores_previous_deletions(self):
        original=Path.unlink
        def unlink(path,*args,**kwargs):
            if path==self.static:raise PermissionError('cache locked')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',unlink):
            with self.assertRaisesRegex(PermissionError,'cache locked'):self.installer.install()
        self.assertEqual(self.cache.read_bytes(),b'old small model')
        self.assertEqual(self.static.read_bytes(),b'old static model')
        self.assertFalse((self.game/'Data/ModVDF'/self.config.filename).exists())

    def test_independent_launch_cleans_before_starting_game(self):
        self.installer.install()
        self.cache.write_bytes(b'cache created by last launch')
        def start(*args,**kwargs):
            self.assertFalse(self.cache.exists())
            return Mock(pid=42)
        with patch('gothic_editor.core.mod_launch.starter_supports_direct',return_value=True), \
                patch('gothic_editor.core.mod_launch.subprocess.Popen',side_effect=start) as spawn:
            ModLauncherService(self.project,self.game,self.config).launch()
        spawn.assert_called_once()
        self.assertIn('SKILL_POTION.MRM',(self.project/'logs/launch.log').read_text('utf-8'))

    def test_invalid_build_does_not_touch_game_cache(self):
        self.archive.write_bytes(b'broken mod')
        with self.assertRaises(ValueError):self.installer.install()
        self.assertEqual(self.cache.read_bytes(),b'old small model')

    def test_resolved_cache_directory_cannot_escape_game_root(self):
        outside=self.root/'outside'
        outside.mkdir()
        keep=outside/'skill_potion.mrm'
        keep.write_bytes(b'keep external model')
        with patch('gothic_editor.core.mesh_cache.target_path',return_value=outside):
            with self.assertRaises(ValueError):MeshCache(self.project,self.game).plan(self.files)
        self.assertEqual(keep.read_bytes(),b'keep external model')
