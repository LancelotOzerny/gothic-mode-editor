import math
import struct
import tempfile
import tkinter as tk
import unittest
from concurrent.futures import Future
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.archive_models import ArchiveModels, load_archive_model, _load_archive_model
from gothic_editor.core.mesh import MeshFormatError, read_mrm, read_3ds_bytes
from gothic_editor.core.model_export import export_model_3ds
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.settings import SettingsStore
from gothic_editor.core.vdf import VdfArchive, VdfFormatError


VERTICES = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (0., 0., 1.)]


def mrm_bytes(version=0x905, indices=(2, 0, 1), second_submesh=False):
    content = b''.join(struct.pack('<fff', *vertex) for vertex in VERTICES)
    sections = []
    for mapping in (indices, (3, 2, 1)) if second_submesh else (indices,):
        triangle_offset = len(content)
        content += struct.pack('<HHH', 0, 1, 2)
        wedge_offset = len(content)
        content += b''.join(struct.pack('<5fHH', 0, 0, 1, 0, 0, index, 0) for index in mapping)
        sections.append(struct.pack('<20I', triangle_offset, 1, wedge_offset, 3, *([0] * 16)))
    metadata = struct.pack('<B4I', len(sections), 0, 4, 0, 0) + b''.join(sections)
    payload = struct.pack('<HI', version, len(content)) + content + metadata
    return struct.pack('<HI', 0xB100, len(payload)) + payload + struct.pack('<HI', 0xB1FF, 0)


def write_vdf(path, files, timestamp=0, version=0x50, signature=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    # A real directory entry precedes the model entries.
    count = len(files) + 1
    offset = 296 + count * 80
    catalog = struct.pack('<64s4I', b'MESHES', 1, 0, 0xC0000000, 0)
    payload = b''
    for index, (name, data) in enumerate(files.items()):
        catalog += struct.pack('<64s4I', name.encode().ljust(64, b' '), offset + len(payload),
                               len(data), 0x40000000 if index == len(files) - 1 else 0, 0)
        payload += data
    signature = signature or VdfArchive.SIGNATURES[1]
    header = struct.pack('<256s16s6I', b'', signature, count, len(files), timestamp,
                         offset + len(payload), 296, version)
    path.write_bytes(header + catalog + payload)
    return path


def source_3ds_bytes():
    def chunk(kind, payload):
        return struct.pack('<HI', kind, len(payload) + 6) + payload
    vertices = chunk(0x4110, struct.pack('<H', 4) + b''.join(struct.pack('<fff', *v) for v in VERTICES))
    faces = chunk(0x4120, struct.pack('<H4H', 1, 0, 1, 2, 0))
    return chunk(0x4D4D, chunk(0x3D3D, chunk(0x4000, b'model\0' + chunk(0x4100, vertices + faces))))


class ModelFormatTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        _load_archive_model.cache_clear()

    def test_export_copies_source_3ds_and_converts_archived_mrm(self):
        archives=ArchiveModels()
        write_vdf(self.root/'game/Data/Meshes.vdf',{'POTION.MRM':mrm_bytes(second_submesh=True)})
        archives.refresh(self.root/'project',self.root/'game')
        output=self.root/'export.3ds'
        self.assertTrue(export_model_3ds('POTION.3DS',{},archives,output))
        self.assertEqual(read_3ds_bytes(output.read_bytes()),(VERTICES,[(2,0,1),(3,2,1)]))
        source=self.root/'POTION.3DS'
        source.write_bytes(source_3ds_bytes())
        self.assertFalse(export_model_3ds('POTION.3DS',{'potion.3ds':source},archives,output))
        self.assertEqual(output.read_bytes(),source.read_bytes())
        write_vdf(self.root/'game/Data/Meshes.vdf',{'POTION.3DS':source_3ds_bytes()})
        archives.refresh(self.root/'project',self.root/'game')
        self.assertFalse(export_model_3ds('POTION.3DS',{},archives,output))
        self.assertEqual(output.read_bytes(),source.read_bytes())

    def test_export_missing_or_broken_model_preserves_existing_destination(self):
        archives=ArchiveModels()
        output=self.root/'export.3ds'
        output.write_bytes(b'previous model')
        with self.assertRaises(ValueError):
            export_model_3ds('MISSING.3DS',{},archives,output)
        write_vdf(self.root/'game/Data/Meshes.vdf',{'POTION.MRM':b'broken'})
        archives.refresh(self.root/'project',self.root/'game')
        with self.assertRaises(MeshFormatError):
            export_model_3ds('POTION.3DS',{},archives,output)
        self.assertEqual(output.read_bytes(),b'previous model')

    def test_mrm_wedges_multiple_submeshes_and_versions(self):
        for version in (0x305, 0x805, 0x905):
            vertices, faces = read_mrm(mrm_bytes(version, second_submesh=True))
            self.assertEqual(vertices, VERTICES)
            self.assertEqual(faces, [(2, 0, 1), (3, 2, 1)])

    def test_mrm_rejects_truncation_invalid_indices_offsets_and_nonfinite_vertices(self):
        data = mrm_bytes()
        invalid_index = mrm_bytes(indices=(2, 0, 100))
        invalid_offset = bytearray(data)
        content_size = struct.unpack_from('<I', data, 8)[0]
        struct.pack_into('<I', invalid_offset, 12 + content_size + 1, 0xFFFFFFFF)
        invalid_float = bytearray(data)
        struct.pack_into('<f', invalid_float, 12, math.inf)
        for broken in (b'', data[:30], data[:-90], invalid_index, invalid_offset, invalid_float,
                       mrm_bytes(version=0xFFFF)):
            with self.subTest(size=len(broken)), self.assertRaises(MeshFormatError):
                read_mrm(broken)

    def test_vdf_signatures_padding_and_targeted_read(self):
        for index, signature in enumerate(VdfArchive.SIGNATURES):
            path = write_vdf(self.root / f'{index}.vdf', {'POTION.MRM': mrm_bytes()}, signature=signature)
            archive = VdfArchive(path)
            self.assertEqual(list(archive.entries), ['potion.mrm'])
            self.assertEqual(load_archive_model(archive.entries['potion.mrm'])[1], [(2, 0, 1)])

    def test_broken_and_compressed_archives_report_errors(self):
        path = self.root / 'bad.vdf'
        path.write_bytes(b'bad')
        with self.assertRaises(VdfFormatError):
            VdfArchive(path)
        write_vdf(path, {'POTION.MRM': mrm_bytes()}, version=0xA0)
        with self.assertRaises(VdfFormatError):
            VdfArchive(path)
        write_vdf(path, {'POTION.MRM': mrm_bytes()})
        data = bytearray(path.read_bytes())
        struct.pack_into('<I', data, 296 + 80 + 64, len(data) + 10)
        path.write_bytes(data)
        with self.assertRaises(VdfFormatError):
            VdfArchive(path)

    def test_index_resolves_visual_and_prioritizes_project_then_archive_timestamp(self):
        project, game = self.root / 'project', self.root / 'game'
        old = write_vdf(game / 'Data' / 'Meshes.vdf', {'POTION.MRM': mrm_bytes()}, timestamp=1)
        newer = write_vdf(game / 'Data' / 'Patch.VDF', {'POTION.MRM': mrm_bytes()}, timestamp=2)
        write_vdf(game / 'Data' / 'ModVDF' / 'inactive.mod', {'POTION.MRM': mrm_bytes()}, timestamp=99)
        models = ArchiveModels()
        self.assertEqual(models.refresh(project, game), [])
        entry = models.find(r'folder\PoTiOn.3DS')
        self.assertEqual(entry.archive, newer)
        project_archive = write_vdf(project / 'Data' / 'Project.vdf', {'POTION.MRM': mrm_bytes()})
        models.refresh(project, game)
        self.assertEqual(models.find('potion.mrm').archive, project_archive)
        self.assertIsNone(models.find('potion.asc'))
        self.assertIsNone(models.find('missing.3ds'))
        project_archive.unlink()
        newer.unlink()
        models.refresh(project, game)
        self.assertEqual(models.find('potion.3ds').archive, old)
        models.refresh(project, None)
        self.assertIsNone(models.find('potion.3ds'))

    def test_archive_source_3ds_is_supported_and_geometry_is_cached(self):
        path = write_vdf(self.root / 'models.vdf', {'POTION.3DS': source_3ds_bytes(), 'POTION.MRM': mrm_bytes()})
        archive = VdfArchive(path)
        entry = archive.entries['potion.3ds']
        first = load_archive_model(entry)
        self.assertEqual(first, read_3ds_bytes(source_3ds_bytes()))
        with patch('gothic_editor.core.vdf.VdfEntry.read_bytes', side_effect=AssertionError('Cache missed')):
            self.assertIs(load_archive_model(entry), first)

    def test_repository_keeps_broken_archive_error_and_refreshes_changed_catalog(self):
        repo = ProjectRepository()
        repo.create(self.root / 'project', 'Test')
        archive = write_vdf(self.root / 'game/Data/Meshes.vdf', {'FIRST.MRM': mrm_bytes()})
        (archive.parent / 'Broken.vdf').write_bytes(b'bad')
        repo.set_game_path(str(self.root / 'game'))
        self.assertTrue(any('Broken.vdf' in error for error in repo.errors))
        self.assertIsNotNone(repo.archive_models.find('first.3ds'))
        write_vdf(archive, {'SECOND_LONG_NAME.MRM': mrm_bytes()})
        repo.refresh()
        self.assertIsNone(repo.archive_models.find('first.3ds'))
        self.assertIsNotNone(repo.archive_models.find('second_long_name.3ds'))


class ModelViewerIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with patch('gothic_editor.app.SettingsStore', return_value=SettingsStore(self.root / 'settings.json')):
            try:
                self.app = EditorApp()
            except tk.TclError as exc:
                self.skipTest(str(exc))
        self.addCleanup(self.app.destroy)
        self.app.withdraw()
        self.app.repo.create(self.root / 'project', 'Test')
        self.item = self.app.repo.create_item('potions')
        self.item.fields['visual'] = '"POTION.3DS"'
        write_vdf(self.root / 'game/Data/Meshes.vdf', {'POTION.MRM': mrm_bytes()})
        self.app.repo.set_game_path(str(self.root / 'game'))
        self.app.show_project()

    def finish_load(self):
        deadline = monotonic() + 5
        while self.app._model_future is not None and monotonic() < deadline:
            self.app.update()
        self.assertIsNone(self.app._model_future)

    def test_context_menu_exports_clicked_item_and_cancel_does_not_write(self):
        from types import SimpleNamespace
        output=self.root/'downloaded.3ds'
        with patch('tkinter.Menu.tk_popup'):
            self.app.hierarchy.context(SimpleNamespace(x_root=0,y_root=0),self.item)
        menu=self.app.hierarchy._context_menu
        self.assertEqual(menu.entrycget(2,'label'),'Скачать модель → 3DS')
        with patch('gothic_editor.app.filedialog.asksaveasfilename',return_value=str(output)):
            menu.invoke(2)
        self.assertEqual(read_3ds_bytes(output.read_bytes()),(VERTICES,[(2,0,1)]))
        self.assertIn(str(output),self.app.status.get())
        with patch('gothic_editor.app.filedialog.asksaveasfilename',return_value=''), \
                patch('gothic_editor.app.export_model_3ds') as export:
            self.app.export_model(self.item)
        export.assert_not_called()

    def test_missing_source_loads_archive_and_existing_source_has_priority(self):
        self.app.select(self.item)
        self.finish_load()
        self.assertEqual(self.app.viewer.faces, [(2, 0, 1)])
        self.assertIn('Meshes.vdf', self.app.viewer.caption)
        source = self.root / 'project/Assets/Models/POTION.3DS'
        source.write_bytes(source_3ds_bytes())
        self.app.repo.refresh()
        self.app.select(self.item)
        self.assertEqual(self.app.viewer.faces, [(0, 1, 2)])
        self.assertEqual(self.app.viewer.caption, 'POTION.3DS')
        source.unlink()  # File deleted since the last resource scan also falls back.
        self.app.select(self.item)
        self.finish_load()
        self.assertEqual(self.app.viewer.faces, [(2, 0, 1)])

    def test_stale_background_result_does_not_replace_new_selection(self):
        future = Future()
        with patch.object(self.app._model_executor, 'submit', return_value=future):
            self.app.select(self.item)
        entry = self.app.repo.archive_models.find(self.item.visual)
        self.item.fields['visual'] = '"MISSING.3DS"'
        self.app.select(self.item)
        caption = self.app.viewer.caption
        self.app._finish_archive_model(future, entry)
        self.assertEqual(self.app.viewer.caption, caption)
        self.assertFalse(self.app.viewer.vertices)

    def test_invalid_model_is_displayed_without_crashing(self):
        write_vdf(self.root / 'game/Data/Meshes.vdf', {'POTION.MRM': b'broken'})
        self.app.repo.refresh()
        self.app.select(self.item)
        self.finish_load()
        self.assertFalse(self.app.viewer.vertices)
        self.assertIn('MRM', self.app.viewer.caption)


if __name__ == '__main__':
    unittest.main()
