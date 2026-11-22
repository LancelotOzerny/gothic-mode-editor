"""Regression tests for packed Gothic BINARY VOB tree parsing."""
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gothic_editor.core.zen_binary_vobs import read_binary_vobs
from gothic_editor.core.world_vobs import _unpack_vob, static_vobs
from gothic_editor.core.zen_world import inspect_zen


def obj(name, classes, body, version=0):
    name = name.encode('cp1252') + b'\0'
    classes = classes.encode('cp1252') + b'\0'
    size = 10 + len(name) + len(classes) + len(body)
    return struct.pack('<IHI', size, version, 1) + name + classes + body


def packed_vob(name, visual, x, *, gothic2=True):
    bbox = (0.,) * 6
    position = (float(x), 20., -30.)
    rotation = (1., 0., 0., 0., 1., 0., 0., 0., 1.)
    raw = struct.pack('<18f', *(bbox + position + rotation))
    if gothic2:
        raw += struct.pack('<BHff', 1, 0b110, 0., 1.)
    else:
        raw += bytes((1, 0b110))
    return (struct.pack('<i', 1) + raw +
            name.encode('cp1252') + b'\0' +
            visual.encode('cp1252') + b'\0')


class BinaryVobTests(unittest.TestCase):
    def test_packed_gothic2_and_nested_tree(self):
        first = obj('root', 'zCVob', packed_vob('First', 'TREE.3DS', 10.))
        second = obj('child', 'zCVob', packed_vob('Child', 'ROCK.3DS', 6100.))
        tree = obj('VobTree', '%',
                   struct.pack('<i', 1) + first +
                   struct.pack('<i', 1) + second +
                   struct.pack('<i', 0))
        mesh = obj('MeshAndBsp', '%', struct.pack('<I', 0x4090000))
        binary = obj('%', 'oCWorld:zCWorld', mesh + tree)
        header = (b'ZenGin Archive\nver 1\nzCArchiverGeneric\nBINARY\n'
                  b'saveGame 0\nEND\nobjects 3\nEND\n')
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'OLDWORLD.ZEN'
            path.write_bytes(header + binary)
            nodes, status = read_binary_vobs(path)
            self.assertEqual(len(nodes), 2)
            self.assertIn('BINARY', status)
            self.assertEqual(nodes[1].parent_index, 0)
            info = inspect_zen(path)
            info = type(info)(info.source, info.encoding, info.archiver,
                              info.version, info.is_save, info.object_count,
                              nodes, False, True, True)
            objects, _, skipped = static_vobs(info, 6000)
            self.assertEqual(len(objects), 2)
            self.assertEqual(skipped, 0)
            self.assertEqual(objects[0].position, (10., 20., -30.))
            self.assertEqual(objects[1].chunk, (1, -1))

    def test_packed_gothic1_world(self):
        tree = obj('VobTree', '%',
                   struct.pack('<i', 1) +
                   obj('root', 'zCVob',
                       packed_vob('Tree', 'TREE.3DS', -200., gothic2=False)) +
                   struct.pack('<i', 0))
        mesh = obj('MeshAndBsp', '%', struct.pack('<I', 0x2090000))
        world = obj('%', 'oCWorld:zCWorld', mesh + tree)
        header = (b'ZenGin Archive\nver 1\nzCArchiverGeneric\nBINARY\n'
                  b'saveGame 0\nEND\nobjects 3\nEND\n')
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'OLDWORLD.ZEN'
            path.write_bytes(header + world)
            nodes, _ = read_binary_vobs(path)
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0].properties['visual'], 'TREE.3DS')
            self.assertEqual(nodes[0].properties['trafoOSToWSPos'],
                             '-200.0 20.0 -30.0')

    def test_packed_binsafe_coordinates(self):
        raw = struct.pack('<18f', *((0.,)*6 + (25., 100., 75.) +
                   (1., 0., 0., 0., 1., 0., 0., 0., 1.)))
        raw += struct.pack('<BHff', 1, 4, 0., 1.)
        pos, rot, visible = _unpack_vob(raw.hex())
        self.assertEqual(pos, (25., 100., 75.))
        self.assertTrue(visible)
        self.assertEqual(rot[0], 1.)

    def test_gothic1_packed_layout(self):
        raw = struct.pack('<18f', *((0.,)*6 + (5., 10., 15.) +
                   (1., 0., 0., 0., 1., 0., 0., 0., 1.))) + bytes((1, 4))
        pos, _, visible = _unpack_vob(raw.hex())
        self.assertEqual(pos, (5., 10., 15.))
        self.assertTrue(visible)


if __name__ == '__main__':
    unittest.main()
