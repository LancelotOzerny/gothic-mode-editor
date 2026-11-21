"""World wireframe sampling and camera math tests (Tk is not required)."""
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from gothic_editor.core.world_preview import (
    MAX_PREVIEW_TRIANGLES, prepare_wireframe, project_wireframe,
    available_locations, is_location_zen, load_world_wireframe, build_world_chunks, face_color,
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

    def test_spatial_chunks_only_show_nearby_faces(self):
        geometry = SimpleNamespace(
            vertices=((0., 0., 0.), (100., 0., 0.), (0., 0., 100.),
                      (6000., 0., 0.), (6100., 0., 0.), (6000., 0., 100.),
                      (18000., 0., 0.), (18100., 0., 0.), (18000., 0., 100.)),
            triangles=((0, 1, 2), (3, 4, 5), (6, 7, 8)),
            vertex_count=9, triangle_count=3)
        world = build_world_chunks(geometry, 6000)
        self.assertEqual(set(world.chunks), {(0, 0), (1, 0), (3, 0)})
        near = world.view((0, 0), radius=0)
        self.assertEqual(len(near.faces), 1)
        self.assertEqual(near.vertices, geometry.vertices[:3])
        wider = world.view((0, 0), radius=1)
        self.assertEqual(len(wider.faces), 2)
        far = world.view((3, 0), radius=0)
        self.assertEqual(far.vertices, geometry.vertices[6:9])

    def test_visible_chunk_triangle_budget(self):
        vertices = []
        faces = []
        for chunk in range(4):
            for face in range(40):
                first = len(vertices)
                x = chunk * 6000 + face
                vertices.extend(((x, 0., 0.), (x+1, 0., 0.), (x, 0., 1.)))
                faces.append((first, first+1, first+2))
        geometry = SimpleNamespace(
            vertices=tuple(vertices), triangles=tuple(faces),
            vertex_count=len(vertices), triangle_count=len(faces))
        world = build_world_chunks(geometry, 6000)
        self.assertEqual(len(world.chunks), 4)
        scene = world.view((1, 0), radius=2, triangle_limit=13)
        self.assertEqual(len(scene.faces), 13)
        self.assertTrue(all(max(face) < len(scene.vertices) for face in scene.faces))
        self.assertTrue(all(math.isfinite(x) for point in
                            project_wireframe(scene, 800, 600, 0.55, -0.45, 1.)
                            for x in point))
        with self.assertRaises(ValueError):
            build_world_chunks(geometry, 0)

    def test_chunked_view_excludes_invalid_geometry(self):
        geometry = SimpleNamespace(
            vertices=((0., 0., 0.), (1., 0., 0.), (0., 0., 1.),
                      (float('nan'), 0., 1.)),
            triangles=((0, 1, 2), (0, 1, 3)), vertex_count=4, triangle_count=2)
        world = build_world_chunks(geometry, 6000)
        self.assertEqual(world.discarded_triangles, 1)
        self.assertEqual(len(world.view((0, 0), radius=0).faces), 1)

    def test_subnormal_bounds_do_not_overflow_projection(self):
        # A world decoded with subnormal floats used to yield infinite scale.
        tiny = SimpleNamespace(
            vertices=((0., 0., 0.), (1e-45, 0., 0.), (0., 1e-45, 0.)),
            triangles=((0, 1, 2),), vertex_count=3, triangle_count=1)
        scene = prepare_wireframe(tiny)
        points = project_wireframe(scene, 900, 600, 0.55, -0.45, 1.)
        self.assertEqual(len(points), 3)
        self.assertTrue(all(math.isfinite(value) for point in points for value in point))

    def test_many_vertices_do_not_change_camera_rotation(self):
        # Regression: screen Y used to overwrite sin(yaw) after each vertex.
        # The original bug failed for ordinary real-world coordinates.
        normal = SimpleNamespace(
            vertices=((-17285.296875, 6805.56982421875, 34216.78125),
                      (-64800.328125, -61526.6953125, -106593.5078125),
                      (61692.0234375, 49574.953125, 44897.93359375)),
            triangles=((0, 1, 2),), vertex_count=3, triangle_count=1)
        scene = prepare_wireframe(normal)
        repeated = type(scene)(
            vertices=scene.vertices * 3000, faces=scene.faces,
            total_vertices=scene.total_vertices,
            total_triangles=scene.total_triangles)
        result = project_wireframe(repeated, 1020, 629, 0.55, -0.45, 1.)
        self.assertEqual(len(result), 9000)
        self.assertTrue(all(math.isfinite(v) for point in result for v in point))
        for index in range(3):
            self.assertEqual(result[index], result[index + 3])

    def test_fixed_camera_frame_keeps_scale_when_changing_chunks(self):
        geometry = SimpleNamespace(
            vertices=((0., 0., 0.), (100., 0., 0.), (0., 0., 100.),
                      (12000., 0., 0.), (12100., 0., 0.), (12000., 0., 100.)),
            triangles=((0, 1, 2), (3, 4, 5)),
            vertex_count=6, triangle_count=2)
        world = build_world_chunks(geometry, 6000)
        scene_left = world.view((0, 0), radius=0)
        scene_right = world.view((2, 0), radius=0)
        left = project_wireframe(scene_left, 800, 600, .4, -.3, 1.,
                                 center=(3000., 0., 3000.), span=6000)
        right = project_wireframe(scene_right, 800, 600, .4, -.3, 1.,
                                  center=(15000., 0., 3000.), span=6000)
        left_edge = math.dist(left[0][:2], left[1][:2])
        right_edge = math.dist(right[0][:2], right[1][:2])
        self.assertAlmostEqual(left_edge, right_edge, places=6)

    def test_surface_shading_valid_for_flat_and_degenerate_faces(self):
        scene = prepare_wireframe(self.geometry)
        for face in scene.faces:
            shade = face_color(scene.vertices, face)
            self.assertRegex(shade, r'^#[0-9a-f]{6}
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
)
        self.assertEqual(face_color(scene.vertices, (0, 0, 0)), '#344151')

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
