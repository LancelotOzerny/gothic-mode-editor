"""Regression checks for nonblocking world texture loading and prefetch."""
from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import struct
import unittest

from gothic_editor.core.textures import Texture
from gothic_editor.core.world_textures import WorldTextures


def tiny_tga():
    header = struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0,
                         0, 0, 1, 1, 24, 0x20)
    return header + bytes((0, 0, 255))


class WorldTextureQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('A.TGA', 'B.TGA', 'C.TGA'):
            (self.root / name).write_bytes(tiny_tga())
        self.store = WorldTextures(
            {name.lower(): self.root / name for name in ('A.TGA', 'B.TGA', 'C.TGA')})
        self.addCleanup(self.store.close)

    def test_finished_offscreen_futures_free_slots(self):
        finished = Future()
        finished.set_result(Texture(1, 1, bytes((255, 0, 0, 255))))
        self.store._pending['a.tga'] = finished
        self.store._max_pending = 1
        with patch.object(self.store._executor, 'submit', wraps=self.store._executor.submit):
            self.store.prefetch(['B.TGA'])
        self.assertNotIn('a.tga', self.store._pending)
        self.assertIn('b.tga', self.store._pending)
        self.assertEqual(self.store.request('A.TGA').pixels, bytes((255, 0, 0, 255)))

    def test_prefetch_schedules_once_for_repeated_names(self):
        unresolved = Future()
        with patch.object(self.store._executor, 'submit', return_value=unresolved) as submit:
            self.store.prefetch(['A.TGA', 'A.TGA', 'A.TGA'])
            self.store.request('A.TGA')
            submit.assert_called_once()
        self.assertEqual(list(self.store._pending), ['a.tga'])

    def test_decode_orientation_and_single_pixel(self):
        image = self.store._decode(self.root / 'A.TGA')
        self.assertEqual((image.width, image.height), (1, 1))
        self.assertEqual(image.pixels, bytes((255, 0, 0, 255)))

    def test_loose_index_pending_does_not_mark_texture_missing(self):
        future = Future()
        self.store._index_future = future
        self.assertIsNone(self.store.request('UNLISTED.TGA'))
        self.assertNotIn('unlisted.tga', self.store._missing)
        future.set_result({'unlisted.tga': self.root / 'A.TGA'})
        self.assertIsNone(self.store.request('UNLISTED.TGA'))
        self.assertIn('unlisted.tga', self.store._pending)


if __name__ == '__main__':
    unittest.main()
