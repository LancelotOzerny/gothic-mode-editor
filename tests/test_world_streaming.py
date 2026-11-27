"""CPU-only regression coverage for indexed world streaming buffers and cache."""
import tempfile
import unittest
from pathlib import Path
from struct import iter_unpack

from gothic_editor.core.world_streaming import (WorldDiskCache, build_batches,
    decode_batches, encode_batches, prepare_batches, source_stamp)


class WorldStreamingTests(unittest.TestCase):
    def test_indexed_buffers_preserve_triangles_and_uvs(self):
        vertices = ((0.,0.,0.), (1.,0.,0.), (0.,0.,1.))
        faces = ((0,1,2), (0,1,2))
        uv = ((0.,0.), (1.,0.), (0.,1.))
        batches = build_batches(vertices, faces, (uv,uv), ('A.TGA','A.TGA'))
        name, data, indices = batches[0]
        self.assertEqual(name, 'a.tga')
        self.assertEqual(len(data), 3*32)
        self.assertEqual([x[0] for x in iter_unpack('<I',indices)], [0,1,2,0,1,2])
        self.assertEqual(decode_batches(encode_batches(batches)), batches)

    def test_disk_cache_hit_and_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'world.zen'
            source.write_bytes(b'one')
            cache = WorldDiskCache(root / 'cache')
            vertices = ((0.,0.,0.), (1.,0.,0.), (0.,0.,1.))
            args = (vertices, ((0,1,2),), (), ())
            first, _, hit = prepare_batches(cache, source_stamp(source), *args)
            self.assertFalse(hit)
            second, _, hit = prepare_batches(cache, source_stamp(source), *args)
            self.assertTrue(hit)
            self.assertEqual(first, second)
            source.write_bytes(b'changed')
            _, _, hit = prepare_batches(cache, source_stamp(source), *args)
            self.assertFalse(hit)

    def test_corrupt_cache_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = WorldDiskCache(directory)
            cache.write(cache.key('geometry', 'test'), b'bad')
            batches, _, hit = prepare_batches(cache, 'test',
                ((0.,0.,0.), (1.,0.,0.), (0.,0.,1.)), ((0,1,2),), (), ())
            self.assertFalse(hit)
            self.assertEqual(len(batches), 1)


if __name__ == '__main__':
    unittest.main()
