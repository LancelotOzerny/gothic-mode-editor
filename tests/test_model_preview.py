"""Preview tests with synthetic resources; never load the working potion schema."""
import math
from pathlib import Path
import struct
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from concurrent.futures import Future
from time import monotonic
from time import sleep

from gothic_editor.core.archive_models import ArchiveModels
from gothic_editor.core.mesh import PreviewMesh, read_3ds_bytes, read_mrm
from gothic_editor.core.mesh_materials import mrm_textures
from gothic_editor.core.model_preview import ModelPreview, load_model_preview
from gothic_editor.core.preview_render import render_mesh, project_vertices, sample_texture
from gothic_editor.core.textures import Texture, read_tga, read_ztex
from gothic_editor.ui.panels.viewer import ModelViewer
from gothic_editor.app import EditorApp
from gothic_editor.core.scripts import Item
from gothic_editor.core.settings import SettingsStore
from test_models import mrm_bytes, write_vdf


def chunk(kind, payload):
    return struct.pack('<HI', kind, len(payload) + 6) + payload


def textured_3ds():
    vertices = chunk(0x4110, struct.pack('<H9f', 3, -1, -1, 0, 1, -1, 0, 0, 1, 0))
    faces = chunk(0x4120, struct.pack('<H4H', 1, 0, 1, 2, 0)
                  + chunk(0x4130, b'bottle\0' + struct.pack('<HH', 1, 0)))
    uvs = chunk(0x4140, struct.pack('<H6f', 3, 0, 0, 1, 0, .5, 1))
    material = chunk(0xAFFF, chunk(0xA000, b'bottle\0')
                     + chunk(0xA200, chunk(0xA300, b'Bottle.TGA\0')))
    mesh = chunk(0x4000, b'bottle\0' + chunk(0x4100, vertices + faces + uvs))
    return chunk(0x4D4D, chunk(0x3D3D, mesh + material))


def material_archive(*names):
    data = b'ZenGin Archive\nver 1\nzCArchiverGeneric\nBINARY\nsaveGame 0\nEND\nobjects 2\nEND\n\n'
    for name in names:
        body = b'material\0zCMaterial\0bottle\0' + bytes(9) + name.encode() + b'\0ignored remainder'
        data += b'bottle\0' + struct.pack('<IHI', 10 + len(body), 0x9C03, 0) + body
    return data


def tga(rgb=(255, 0, 0)):
    return struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0, 2, 2, 24, 32) + bytes(reversed(rgb)) * 4


def ztex(kind, pixels, width=4, height=4, levels=1):
    return b'ZTEX' + struct.pack('<8I', 0, kind, width, height, levels, width, height, 0) + pixels


class PreviewFormatTests(unittest.TestCase):
    def test_3ds_face_material_and_uvs_are_separate_from_export_geometry(self):
        mesh = read_3ds_bytes(textured_3ds(), preview=True)
        self.assertEqual(mesh.texture_names, ['Bottle.TGA'])
        self.assertEqual(mesh.uvs, [((0, 1), (1, 1), (.5, 0))])
        self.assertEqual(read_3ds_bytes(textured_3ds()), (mesh.vertices, mesh.faces))

    def test_mrm_binary_materials_and_per_wedge_uvs(self):
        archive = material_archive('Bottle.TGA', 'Second.TGA')
        self.assertEqual(mrm_textures(archive, 2), ['Bottle.TGA', 'Second.TGA'])
        self.assertEqual(mrm_textures(archive.replace(b'BINARY', b'ASCII'), 2), ['', ''])
        original = mrm_bytes(second_submesh=True)
        size = struct.unpack_from('<I', original, 2)[0]
        payload = bytearray(original[6:6 + size])
        content_size = struct.unpack_from('<I', payload, 2)[0]
        wedge_offset = struct.unpack_from('<I', payload, 6 + content_size + 17 + 8)[0]
        struct.pack_into('<ff', payload, 6 + wedge_offset + 12, .25, .75)
        payload.extend(archive)
        mesh = read_mrm(struct.pack('<HI', 0xB100, len(payload)) + payload, preview=True)
        self.assertEqual(mesh.texture_names, ['Bottle.TGA', 'Second.TGA'])
        self.assertEqual(mesh.uvs[0][0], (.25, .75))
        self.assertEqual(mesh.faces, [(2, 0, 1), (3, 2, 1)])

    def test_tga_orientation_rle_palette_and_truncation(self):
        header = struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0, 1, 2, 24, 0)
        self.assertEqual(read_tga(header + b'\xff\x00\x00\x00\x00\xff').pixels,
                         bytes((255, 0, 0, 255, 0, 0, 255, 255)))
        encoded = bytearray(tga())
        encoded[2] = 10
        self.assertEqual(read_tga(bytes(encoded[:18]) + b'\x83\x00\x00\xff').pixels,
                         bytes((255, 0, 0, 255)) * 4)
        indexed = struct.pack('<BBBHHBHHHHBB', 0, 1, 1, 3, 1, 24, 0, 0, 1, 1, 8, 32)
        self.assertEqual(read_tga(indexed + b'\x00\xff\x00\x03').pixels, bytes((0, 255, 0, 255)))
        unused_alpha = struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0, 1, 1, 32, 32)
        self.assertEqual(read_tga(unused_alpha + bytes((0, 0, 255, 0))).pixels, bytes((255, 0, 0, 255)))
        for broken in (b'', tga()[:-1], bytes(encoded[:18]) + b'\xff\x00\x00\xff'):
            with self.assertRaises(ValueError):
                read_tga(broken)

    def test_ztex_raw_mipmap_order_and_dxt_alpha(self):
        raw = ztex(0, bytes((0, 255, 0, 255)) + bytes((0, 0, 255, 255)) * 4, 2, 2, 2)
        self.assertEqual(read_ztex(raw).pixels, bytes((255, 0, 0, 255)) * 4)
        color = struct.pack('<HHI', 0xF800, 0x07E0, 0)
        self.assertEqual(read_ztex(ztex(10, color)).pixels, bytes((255, 0, 0, 255)) * 16)
        for kind in (11, 12):
            self.assertEqual(read_ztex(ztex(kind, b'\xff' * 8 + color)).pixels,
                             bytes((255, 0, 0, 255)) * 16)
        for kind in (13, 14):
            self.assertEqual(read_ztex(ztex(kind, bytes((255, 0)) + bytes(6) + color)).pixels,
                             bytes((255, 0, 0, 255)) * 16)
        transparent = struct.pack('<HHI', 0, 0xFFFF, 0xFFFFFFFF)
        self.assertEqual(read_ztex(ztex(10, transparent)).pixels, bytes(64))
        for broken in (b'ZTEX', raw[:-1], ztex(10, color[:-1])):
            with self.assertRaises(ValueError):
                read_ztex(broken)

    def test_texture_resolution_archives_local_override_missing_and_corrupt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'bottle.3ds'
            source.write_bytes(textured_3ds())
            color = struct.pack('<HHI', 0x07E0, 0xF800, 0)
            write_vdf(root / 'game/Data/Textures.vdf', {'BOTTLE-C.TEX': ztex(10, color)})
            archives = ArchiveModels()
            self.assertEqual(archives.refresh(root / 'project', root / 'game'), [])
            self.assertFalse(archives.entries)
            entry = archives.texture_entries['bottle-c.tex']
            preview = load_model_preview(source, root / 'project', texture_entries=archives.texture_entries)
            self.assertEqual(preview.textures['Bottle.TGA'].pixels[:4], bytes((0, 255, 0, 255)))
            local = root / 'bOtTlE.tGa'
            local.write_bytes(tga())
            preview = load_model_preview(source, root / 'project', texture_entries=archives.texture_entries)
            self.assertEqual(preview.textures['Bottle.TGA'].pixels[:4], bytes((255, 0, 0, 255)))
            local.write_bytes(b'broken')
            preview = load_model_preview(source, root / 'project')
            self.assertEqual(preview.missing, ['Bottle.TGA'])
            self.assertTrue(preview.mesh.faces)
            project_archive = write_vdf(root / 'project/Data/Textures.vdf', {'BOTTLE-C.TEX': ztex(10, color)})
            archives.refresh(root / 'project', root / 'game')
            self.assertEqual(archives.texture_entries['bottle-c.tex'].archive, project_archive)
            write_vdf(root / 'Data/models.vdf', {'BOTTLE.3DS': textured_3ds()})
            archives.refresh(root, None)
            preview = load_model_preview(archives.find('bottle.3ds'), root,
                                         texture_entries={'bottle-c.tex': entry})
            self.assertFalse(preview.missing)


class PreviewRenderTests(unittest.TestCase):
    def test_minified_checkerboard_is_stable_and_mipmaps_preserve_alpha(self):
        pixels = b''.join(bytes((value, value, value, 255))
                          for y in range(64) for x in range(64) for value in (255*((x+y)%2),))
        texture = Texture(64, 64, pixels)
        self.assertIs(texture.mipmaps, texture.mipmaps)
        self.assertEqual(texture.mipmaps[-1].pixels, bytes((128, 128, 128, 255)))
        mesh = read_3ds_bytes(textured_3ds(), preview=True)
        mesh.uvs = [((0, 0), (32, 0), (0, 32))]
        for angle in (0, .2, .5):
            image = render_mesh(mesh, {'Bottle.TGA': texture}, 80, 60, angle, angle)
            colors = {image[i:i+3] for i in range(0, len(image), 3)}
            self.assertEqual(colors, {bytes((25, 30, 41)), bytes((128, 128, 128))})
        transparent = Texture(2, 1, bytes((255, 0, 0, 255, 0, 0, 0, 0)))
        self.assertEqual(transparent.mipmaps[-1].pixels, bytes((255, 0, 0, 128)))
        odd = Texture(3, 1, bytes((0, 0, 0, 255))*2 + bytes((255, 255, 255, 255)))
        self.assertEqual(odd.mipmaps[-1].pixels, bytes((85, 85, 85, 255)))

    def test_bilinear_filter_repeats_and_avoids_dark_transparent_edges(self):
        texture = Texture(2, 1, bytes((255, 0, 0, 255, 0, 255, 0, 255)))
        self.assertEqual(sample_texture(texture, .25, .5), (255, 0, 0, 255))
        self.assertEqual(sample_texture(texture, .5, .5), (128, 128, 0, 255))
        self.assertEqual(sample_texture(texture, -.5, 1.5), sample_texture(texture, .5, .5))
        transparent = Texture(2, 1, bytes((255, 0, 0, 255, 0, 0, 0, 0)))
        self.assertEqual(sample_texture(transparent, .5, .5), (255, 0, 0, 128))

    def test_solid_mode_outlines_shared_edges_and_hides_occluded_edges(self):
        vertices = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
        mesh = PreviewMesh(vertices, [(0, 1, 2), (0, 2, 3)])
        image = render_mesh(mesh, {}, 80, 80, 0, 0, textured=False)
        self.assertEqual(image[(40 * 80 + 40) * 3:(40 * 80 + 40) * 3 + 3], bytes((53, 65, 83)))
        vertices += [(x, y, 1) for x, y, _ in vertices[:4]]
        both = PreviewMesh(vertices, mesh.faces + [(4, 5, 7), (5, 6, 7)])
        front = PreviewMesh(vertices, [(4, 5, 7), (5, 6, 7)])
        self.assertEqual(render_mesh(both, {}, 80, 80, 0, 0, textured=False),
                         render_mesh(front, {}, 80, 80, 0, 0, textured=False))

    def test_texture_mode_depth_transparency_and_full_fit(self):
        mesh = read_3ds_bytes(textured_3ds(), preview=True)
        texture = Texture(2, 1, bytes((255, 0, 0, 255, 0, 255, 0, 255)))
        rgb = render_mesh(mesh, {'Bottle.TGA': texture}, 80, 60, 0, 0)
        colors = {rgb[i:i + 3] for i in range(0, len(rgb), 3)}
        self.assertTrue(any(color[0] > color[1] and color[2] == 0 for color in colors))
        self.assertTrue(any(color[1] > color[0] and color[2] == 0 for color in colors))
        self.assertTrue(any(color[0] > 0 and color[1] > 0 and color[2] == 0 for color in colors))
        solid = render_mesh(mesh, {'Bottle.TGA': texture}, 80, 60, 0, 0, textured=False)
        self.assertNotEqual(rgb, solid)
        self.assertIn(bytes((53, 65, 83)), {solid[i:i + 3] for i in range(0, len(solid), 3)})
        for angle in (0, 1, math.pi):
            for x, y, _ in project_vertices(mesh.vertices, 80, 60, angle, angle, 1):
                self.assertTrue(0 <= x < 80 and 0 <= y < 60)
        back = list(mesh.vertices)
        mesh.vertices += [(x, y, z + 1) for x, y, z in back]
        mesh.faces += [(3, 4, 5)]
        mesh.uvs *= 2
        mesh.texture_names += ['front']
        textures = {'Bottle.TGA': texture, 'front': Texture(1, 1, bytes((0, 0, 255, 255)))}
        image = render_mesh(mesh, textures, 80, 60, 0, 0)
        self.assertEqual(image[(30 * 80 + 40) * 3: (30 * 80 + 40) * 3 + 3], bytes((0, 0, 255)))
        textures['front'] = Texture(1, 1, bytes(4))
        image = render_mesh(mesh, textures, 80, 60, 0, 0)
        self.assertNotEqual(image[(30 * 80 + 40) * 3: (30 * 80 + 40) * 3 + 3], bytes((0, 0, 255)))


class PreviewWidgetTests(unittest.TestCase):
    def finish_frame(self, root, viewer):
        deadline=monotonic()+10
        while monotonic()<deadline:
            root.update()
            if viewer._wanted_key in viewer._frames and viewer.renderer._future is None:return
            sleep(.005)
        self.fail('Background render did not finish')

    def test_default_toggle_selection_camera_and_missing_icons(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('700x500')
        viewer = ModelViewer(root)
        viewer.pack(fill='both', expand=True)
        root.update()
        preview = ModelPreview(read_3ds_bytes(textured_3ds(), preview=True), {'Bottle.TGA': read_tga(tga())}, [])
        viewer.set_preview(preview)
        self.finish_frame(root,viewer)
        self.assertTrue(viewer.textured)
        self.assertTrue(viewer.texture_button.selected)
        self.assertIsNotNone(viewer.image)
        with patch.object(viewer.renderer,'request',wraps=viewer.renderer.request) as request:
            viewer.draw()
            viewer.draw()
            request.assert_not_called()
        self.assertEqual((viewer.image.width(), viewer.image.height()), (viewer.winfo_width()-20, viewer.winfo_height()-110))
        viewer.draw(preview=True)
        viewer.event_generate('<ButtonRelease-1>', x=10, y=70)
        root.update()
        self.assertEqual(viewer.image.width(), viewer.winfo_width()-20)
        camera = viewer.angle_x, viewer.angle_y, viewer.zoom
        with patch.object(viewer.solid_button.icons, 'directory', Path('missing-icons')):
            viewer.solid_button.invoke()
        self.assertFalse(viewer.textured)
        self.assertTrue(viewer.solid_button.selected)
        self.assertIsNone(viewer.solid_button.image)
        self.assertEqual(camera, (viewer.angle_x, viewer.angle_y, viewer.zoom))
        viewer.texture_button.invoke()
        self.assertTrue(viewer.textured)
        viewer.set_mesh(caption='missing')
        self.assertFalse(viewer.vertices)

    def test_ui_callback_runs_while_background_frame_is_pending(self):
        root=tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('800x650')
        viewer=ModelViewer(root)
        viewer.pack(fill='both',expand=True)
        root.update()
        mesh=read_3ds_bytes(textured_3ds(),preview=True)
        mesh.faces*=8
        mesh.uvs*=8
        mesh.texture_names*=8
        viewer.set_preview(ModelPreview(mesh,{'Bottle.TGA':read_tga(tga())},[]))
        responsive=tk.BooleanVar(root,value=False)
        root.after(1,lambda:responsive.set(viewer.renderer._future is not None))
        root.wait_variable(responsive)
        self.assertTrue(responsive.get())
        self.finish_frame(root,viewer)

    def test_render_requests_are_coalesced_and_cancelled_on_destroy(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        viewer = ModelViewer(root)
        root.update()
        with patch.object(viewer, 'draw') as draw:
            for _ in range(20):viewer.request_draw(preview=True)
            viewer.request_draw(preview=False)
            root.update_idletasks()
            draw.assert_called_once_with(preview=False)
        viewer.set_mesh([(-1, -1, 0), (1, -1, 0), (0, 1, 0)], [(0, 1, 2)])
        viewer.change_zoom(1.12)
        self.assertIsNotNone(viewer._quality_after)
        with patch.object(viewer, 'draw') as draw:
            viewer.destroy()
            root.update()
            draw.assert_not_called()

    def test_application_loads_local_and_archived_textures_and_ignores_stale_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('gothic_editor.app.SettingsStore', return_value=SettingsStore(root / 'settings.json')):
                app = EditorApp()
            try:
                app.withdraw()
                app.repo.create(root / 'project', 'Test')
                source = root / 'project/Assets/Models/bottle.3ds'
                source.write_bytes(textured_3ds())
                source.with_name('BOTTLE.TGA').write_bytes(tga())
                app.repo.mesh_index = {'bottle.3ds': source}
                item = Item('MODEL_TEST', root / 'test.d', 'game', '', {'visual': '"BOTTLE.3DS"'}, 0, 0)

                def finish():
                    deadline = monotonic() + 5
                    while app._model_future is not None and monotonic() < deadline:
                        app.update()
                    self.assertIsNone(app._model_future)

                # Isolate the preview path from property schemas being edited by the user.
                with patch.object(app.properties, 'show'):
                    app.select(item)
                    finish()
                    self.assertEqual(app.viewer.textures['Bottle.TGA'].pixels[:4], bytes((255, 0, 0, 255)))
                    self.assertEqual(app.viewer.caption, 'bottle.3ds')
                    app.viewer.set_textured(False)
                    app.repo.mesh_index = {}
                    source.with_name('BOTTLE.TGA').unlink()
                    write_vdf(root / 'project/Data/models.vdf', {'BOTTLE.3DS': textured_3ds(), 'BOTTLE.TGA': tga((0, 255, 0))})
                    app.repo.archive_models.refresh(root / 'project', None)
                    app.select(item, camera=(.2, .3, 2))
                    finish()
                    self.assertEqual(app.viewer.textures['Bottle.TGA'].pixels[:4], bytes((0, 255, 0, 255)))
                    self.assertIn('models.vdf', app.viewer.caption)
                    self.assertFalse(app.viewer.textured)
                    self.assertEqual((app.viewer.angle_x, app.viewer.angle_y, app.viewer.zoom), (.2, .3, 2))
                    future = Future()
                    with patch.object(app._model_executor, 'submit', return_value=future):
                        app.select(item)
                    entry = app.repo.archive_models.find(item.visual)
                    item.fields['visual'] = '"missing.3ds"'
                    app.select(item)
                    app._finish_archive_model(future, entry)
                    self.assertFalse(app.viewer.vertices)
            finally:
                app.destroy()


if __name__ == '__main__':
    unittest.main()
