"""Independent free-flight perspective camera for ZenGin world coordinates.

Pure Python math: reusable by the current Tk preview and future OpenGL renderer.
Coordinates: X right, Y up, Z forward. Positive yaw faces +Z.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin, radians, tan, sqrt, floor, isfinite, pi

MAX_PITCH = radians(85)
NEAR = 10.0
FAR = 600000.0


@dataclass
class FlyCamera:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    speed: float = 4800.0
    sensitivity: float = 0.003

    @property
    def position(self):
        return self.x, self.y, self.z

    def chunk_at(self, size: int):
        return floor(self.x / size), floor(self.z / size)

    def look(self, dx: float, dy: float):
        self.yaw = (self.yaw + dx * self.sensitivity) % (2 * pi)
        self.pitch = max(-MAX_PITCH, min(MAX_PITCH, self.pitch - dy * self.sensitivity))

    def move(self, forward: float, strafe: float, vertical: float, dt: float,
             *, fast: bool = False):
        # Normalize input so diagonals aren't faster.
        length = sqrt(forward * forward + strafe * strafe + vertical * vertical)
        if not length or dt <= 0:
            return
        scale = min(dt, 0.1) * self.speed * (3.0 if fast else 1.0) / max(1.0, length)
        sy, cy = sin(self.yaw), cos(self.yaw)
        self.x += (forward * sy + strafe * cy) * scale
        self.z += (forward * cy - strafe * sy) * scale
        self.y += vertical * scale

    def project(self, vertices, width: int, height: int, *, fov=70.0,
                near=NEAR, far=FAR):
        """Return screen points or None for vertices behind/too near camera.

        The caller must discard faces with any clipped point, pending
        full near-plane polygon clipping in the GPU renderer.
        """
        w, h = max(1, width), max(1, height)
        focal = h / (2 * tan(radians(fov) / 2))
        sy, cy = sin(self.yaw), cos(self.yaw)
        sp, cp = sin(self.pitch), cos(self.pitch)
        result = []
        for vx, vy, vz in vertices:
            x, y, z = vx - self.x, vy - self.y, vz - self.z
            side = x * cy - z * sy
            forward = x * sy + z * cy
            up = y * cp - forward * sp
            depth = y * sp + forward * cp
            if not isfinite(depth) or depth <= near or depth >= far:
                result.append(None)
                continue
            sx = w / 2 + side * focal / depth
            screen_y = h / 2 - up * focal / depth
            result.append((sx, screen_y, depth)
                          if isfinite(sx) and isfinite(screen_y) else None)
        return tuple(result)


def gl_view_rotation(camera: FlyCamera):
    """4x4 column-major view rotation matching FlyCamera.project().

    ZenGin uses +Z forward; OpenGL uses -Z, so Z is inverted here.
    The translation of -camera.position is applied afterwards.
    """
    cy, sy = cos(camera.yaw), sin(camera.yaw)
    cp, sp = cos(camera.pitch), sin(camera.pitch)
    return (
        cy, -sp * sy, -cp * sy, 0.,
        0., cp, -sp, 0.,
        -sy, -sp * cy, -cp * cy, 0.,
        0., 0., 0., 1.,
    )
