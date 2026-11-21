"""World wireframe sampling and camera math tests (Tk is not required)."""
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from gothic_editor.core.world_preview import (
    MAX_PREVIEW_TRIANGLES, prepare_wireframe, project_wireframe,
    available_locations, is_location_zen, load_world_wireframe,
)


class WorldPreviewTests(unittest.TestCase):
    def setUp(self):
        self.geometry = SimpleNamespace(
            vertices=((0., 0., 0.), (10., 0., 0.), (0., 10., 0.), (10., 10., 0.)),
            triangles=((0, 1, 2), (1, 3, 2), (0, 2, 3)),
            vertex_count=4, triangle_count=3,
        )

    def test_sample_preserves_triangle_indices_and_source_counts(self):
        scene = prepare_wireframe(self.geometry, limit=2)
        self.assertEqual(len(scene.faces), 2)
        self.assertEqual(scene.total_vertices, 4)
        self.assertEqual(scene.total_triangles, 3)
        self.assertTrue(all(0 <= index < len(scene.vertices)
                            for face in scene.faces for index in face))

    def test_nonfinite_vertex_is_excluded_before_projection(self):
        invalid = SimpleNamespace(
            vertices=((0., 0., 0.), (10., 0., 0.), (0., 10., 0.),
                      (float('nan'), 2., 3.), (float('inf'), 0., 0.)),
            triangles=((0, 1, 2), (0, 1, 3), (0, 2, 4)),
            vertex_count=5, triangle_count=3,
        )
        scene = prepare_wireframe(invalid)
        self.assertEqual(scene.discarded_triangles, 2)
        self.assertEqual(len(scene.faces), 1)
        points = project_wireframe(scene, 800, 600, 0.2, 0.3, 1.)
        self.assertTrue(all(math.isfinite(value) for point in points for value in point))

    def test_invalid_index_and_large_vertex_are_excluded(self):
        invalid = SimpleNamespace(
            vertices=((0., 0., 0.), (1., 0., 0.), (0., 1., 0.),
                      (1e30, 0., 0.)),
            triangles=((0, 1, 2), (0, 1, 3), (0, 1, 50)),
            vertex_count=4, triangle_count=3,
        )
        scene = prepare_wireframe(invalid)
        self.assertEqual(scene.discarded_triangles, 2)
        self.assertEqual(len(scene.faces), 1)

    def test_all_invalid_faces_keep_scene_empty_without_error(self):
        invalid = SimpleNamespace(
            vertices=((float('nan'), 0., 0.), (1., 0., 0.), (0., 1., 0.)),
            triangles=((0, 1, 2),), vertex_count=3, triangle_count=1,
        )
        scene = prepare_wireframe(invalid)
        self.assertEqual(scene.discarded_triangles, 1)
        self.assertEqual(scene.faces, ())
        self.assertEqual(project_wireframe(scene, 800, 600, 0., 0., 1.), ())

    def test_subnormal_bounds_do_not_overflow_projection(self):
        # A world decoded with subnormal floats used to yield infinite scale.
        tiny = SimpleNamespace(
            vertices=((0., 0., 0.), (1e-45, 0., 0.), (0., 1e-45, 0.)),
            triangles=((0, 1, 2),), vertex_count=3, triangle_count=1)
        scene = prepare_wireframe(tiny)
        points = project_wireframe(scene, 900, 600, 0.55, -0.45, 1.)
        self.assertEqual(len(points), 3)
        self.assertTrue(all(math.isfinite(value) for point in points for value in point))

    def test_projection_center_pan_and_zoom(self):
        scene = prepare_wireframe(self.geometry)
        first = project_wireframe(scene, 600, 400, 0., 0., 1.)
        second = project_wireframe(scene, 600, 400, 0., 0., 2., 10, -20)
        self.assertEqual(len(first), len(scene.vertices))
        self.assertAlmostEqual(second[0][0] - 300, (first[0][0] - 300) * 2 + 10)
        self.assertAlmostEqual(second[0][1] - 200, (first[0][1] - 200) * 2 - 20)
        self.assertTrue(all(math.isfinite(value) for point in second for value in point))

    def test_invalid_preview_limit(self):
        with self.assertRaises(ValueError):
            prepare_wireframe(self.geometry, 0)
        with self.assertRaises(ValueError):
            prepare_wireframe(self.geometry, MAX_PREVIEW_TRIANGLES + 1)

    def test_service_zen_files_are_not_locations(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary) / '_work' / 'data' / 'Worlds'
            folder.mkdir(parents=True)
            for name in ('Lensflare.zen', 'DialogCams.zen',
                         'LIGHTPRESETS.zen', 'NEWWORLD.ZEN'):
                (folder / name).write_bytes(b'')
            self.assertEqual([path.name for path in available_locations(temporary)],
                             ['NEWWORLD.ZEN'])
            for name in ('Lensflare.zen', 'DialogCams.zen', 'LIGHTPRESETS.zen'):
                self.assertFalse(is_location_zen(name))
                with self.assertRaisesRegex(ValueError, 'служебный архив'):
                    load_world_wireframe(folder / name)

    def test_empty_geometry(self):
        empty = SimpleNamespace(vertices=(), triangles=(), vertex_count=0, triangle_count=0)
        scene = prepare_wireframe(empty)
        self.assertEqual(project_wireframe(scene, 400, 300, 0, 0, 1), ())


if __name__ == '__main__':
    unittest.main()
