"""Static VOB placement and shared-model tests without OpenGL/Tk."""
import struct
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from gothic_editor.core.world_vobs import (
    StaticMesh, VobScene, _rotation, static_vobs, load_vob_scene,
)


def entry(name, **properties):
    return SimpleNamespace(name=name, properties=properties)


class VobTests(unittest.TestCase):
    def test_static_vobs_coordinates_visibility_and_rotation(self):
        rotation = struct.pack('<9f', 1, 0, 0, 0, 1, 0, 0, 0, 1).hex()
        info = SimpleNamespace(details_available=True, objects=(
            entry('a', visual='TREE.3DS', trafoOSToWSPos='100 50 -1',
                  trafoOSToWSRot=rotation),
            entry('b', visual='HOUSE.3DS', trafoOSToWSPos='0 0 0',
                  showVisual='0'),
            entry('c', visual='MISSING.3DS', trafoOSToWSPos='NaN 0 0'),
            entry('d', visual='SMOKE.PFX', trafoOSToWSPos='0 0 0'),
        ))
        objects, status, skipped = static_vobs(info, 6000)
        self.assertEqual(status, 'OK')
        self.assertEqual(len(objects), 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(objects[0].chunk, (0, -1))
        self.assertEqual(objects[0].visual, 'tree.3ds')
        self.assertEqual(objects[0].rotation, (1., 0., 0., 0., 1., 0., 0., 0., 1.))

    def test_binary_without_layout_does_not_guess_properties(self):
        objects, status, skipped = static_vobs(
            SimpleNamespace(details_available=False, objects=()), 6000)
        self.assertEqual(objects, ())
        self.assertIn('BINARY', status)

    def test_binsafe_keeps_rotation_raw_and_boolean(self):
        from gothic_editor.core.zen_binsafe import _value
        rotation = struct.pack('<9f', 1, 0, 0, 0, 1, 0, 0, 0, 1)
        stream = BytesIO(struct.pack('<H', len(rotation)) + rotation)
        self.assertEqual(_value(stream, 9, len(rotation)+2, True),
                         rotation.hex())
        visible = BytesIO(struct.pack('<I', 1))
        self.assertEqual(_value(visible, 6, 4, True), '1')

    def test_shared_mesh_loaded_once_for_repeated_instances(self):
        info = SimpleNamespace(details_available=True, objects=(
            entry('tree1', visual='TREE.3DS', trafoOSToWSPos='0 0 0'),
            entry('tree2', visual='TREE.3DS', trafoOSToWSPos='6200 0 0'),
        ))
        mesh = StaticMesh(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)),
                          ((0, 1, 2),))
        source = SimpleNamespace(name='TREE.MRM')
        with patch('gothic_editor.core.world_vobs.inspect_zen', return_value=info), \
             patch('gothic_editor.core.world_vobs._load_mesh', return_value=mesh) as read:
            scene = load_vob_scene('example.zen', {'tree.mrm': source}, 6000)
        read.assert_called_once_with(source)
        self.assertEqual(len(scene.models), 1)
        self.assertEqual(len(scene.objects), 2)
        self.assertEqual(set(scene.chunks), {(0, 0), (1, 0)})


if __name__ == '__main__':
    unittest.main()
