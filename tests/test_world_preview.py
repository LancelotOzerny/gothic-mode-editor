"""World wireframe sampling and camera math tests (Tk is not required)."""
import math
import unittest
from types import SimpleNamespace

from gothic_editor.core.world_preview import (
    MAX_PREVIEW_TRIANGLES, prepare_wireframe, project_wireframe,
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

    def test_empty_geometry(self):
        empty = SimpleNamespace(vertices=(), triangles=(), vertex_count=0, triangle_count=0)
        scene = prepare_wireframe(empty)
        self.assertEqual(project_wireframe(scene, 400, 300, 0, 0, 1), ())


if __name__ == '__main__':
    unittest.main()
