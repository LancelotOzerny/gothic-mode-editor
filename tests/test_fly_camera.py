"""Pure-Python free-flight camera tests, independent of Tk and OpenGL."""
import math
import unittest

from gothic_editor.core.fly_camera import FlyCamera, gl_view_rotation


class FlyCameraTests(unittest.TestCase):
    def test_forward_strafe_and_height(self):
        camera = FlyCamera(speed=1000)
        camera.move(1, 0, 0, 0.1)
        self.assertAlmostEqual(camera.z, 100)
        camera.move(0, 1, 0, 0.1)
        self.assertAlmostEqual(camera.x, 100)
        camera.move(0, 0, 1, 0.1)
        self.assertAlmostEqual(camera.y, 100)
        self.assertEqual(camera.chunk_at(100), (1, 1))

    def test_shift_and_diagonal_normalization(self):
        normal = FlyCamera(speed=1000)
        fast = FlyCamera(speed=1000)
        normal.move(1, 1, 0, 0.1)
        fast.move(1, 0, 0, 0.1, fast=True)
        self.assertAlmostEqual(math.hypot(normal.x, normal.z), 100)
        self.assertAlmostEqual(fast.z, 300)

    def test_look_pitch_is_clamped_and_yaw_rotates_movement(self):
        camera = FlyCamera(speed=1000)
        camera.look(math.pi/2 / camera.sensitivity, -999999)
        self.assertLess(camera.pitch, math.pi/2)
        camera.move(1, 0, 0, .1)
        self.assertAlmostEqual(camera.x, 100, places=5)
        self.assertAlmostEqual(camera.z, 0, places=5)

    def test_perspective_near_plane_and_behind_camera(self):
        camera = FlyCamera()
        vertices = ((0., 0., 100.), (0., 0., -100.),
                    (0., 0., 1.), (100., 0., 100.))
        points = camera.project(vertices, 800, 600)
        self.assertAlmostEqual(points[0][0], 400)
        self.assertAlmostEqual(points[0][1], 300)
        self.assertIsNone(points[1])
        self.assertIsNone(points[2])
        self.assertGreater(points[3][0], points[0][0])

    def test_opengl_rotation_matches_cpu_perspective(self):
        camera = FlyCamera(x=150., y=40., z=-80., yaw=0.55, pitch=-0.4)
        matrix = gl_view_rotation(camera)
        for vertex in ((250., 120., 600.), (200., 30., 240.), (-100., 90., 500.)):
            x, y, z = (coordinate - origin
                       for coordinate, origin in zip(vertex, camera.position))
            side = matrix[0]*x + matrix[4]*y + matrix[8]*z
            up = matrix[1]*x + matrix[5]*y + matrix[9]*z
            depth = -(matrix[2]*x + matrix[6]*y + matrix[10]*z)
            expected = camera.project((vertex,), 800, 600)[0]
            self.assertIsNotNone(expected)
            focal = 600 / (2 * math.tan(math.radians(70) / 2))
            self.assertAlmostEqual(400 + side*focal/depth, expected[0])
            self.assertAlmostEqual(300 - up*focal/depth, expected[1])
            self.assertAlmostEqual(depth, expected[2])

    def test_chunk_boundary_negative_coordinates(self):
        camera = FlyCamera(x=-1, y=100, z=5999)
        self.assertEqual(camera.chunk_at(6000), (-1, 0))
        camera.z = 6000
        self.assertEqual(camera.chunk_at(6000), (-1, 1))


if __name__ == '__main__':
    unittest.main()
