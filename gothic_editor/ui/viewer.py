import math
import struct
import tkinter as tk
from pathlib import Path

class MeshFormatError(Exception):
    pass


def read_3ds(path: Path):
    """Read vertices + triangular faces from a simple 3DS mesh.

    Materials, textures, keyframed animation and Gothic MRM are intentionally
    outside the MVP. Objects are combined into a single mesh.
    """
    data = path.read_bytes()
    if len(data) < 6 or struct.unpack_from('<H', data)[0] != 0x4D4D:
        raise MeshFormatError('Это не файл формата 3DS')
    vertices, faces = [], []

    def chunks(start, stop, visitor):
        pos = start
        while pos + 6 <= min(stop, len(data)):
            cid, size = struct.unpack_from('<HI', data, pos)
            if size < 6 or pos + size > len(data):
                break
            visitor(cid, pos + 6, pos + size)
            pos += size

    def parse_mesh(start, end):
        local_vertices, local_faces = [], []
        def part(cid, a, b):
            nonlocal local_vertices, local_faces
            if cid == 0x4110 and a + 2 <= b:
                n = struct.unpack_from('<H', data, a)[0]
                if a + 2 + n * 12 <= b:
                    local_vertices = [struct.unpack_from('<fff', data, a + 2 + k * 12) for k in range(n)]
            elif cid == 0x4120 and a + 2 <= b:
                n = struct.unpack_from('<H', data, a)[0]
                if a + 2 + n * 8 <= b:
                    local_faces = [struct.unpack_from('<HHH', data, a + 2 + k * 8) for k in range(n)]
        chunks(start, end, part)
        base = len(vertices)
        vertices.extend(local_vertices)
        faces.extend((base+i, base+j, base+k) for i,j,k in local_faces if max(i,j,k) < len(local_vertices))

    def parse(cid, a, b):
        if cid in (0x4D4D, 0x3D3D):
            chunks(a, b, parse)
        elif cid == 0x4000:
            zero = data.find(b'\x00', a, b)
            if zero != -1:
                chunks(zero+1, b, parse)
        elif cid == 0x4100:
            parse_mesh(a, b)

    chunks(0, len(data), parse)
    if not vertices or not faces:
        raise MeshFormatError('В модели не найдены треугольные полигоны')
    return vertices, faces


class ModelViewer(tk.Canvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg='#191e29', highlightthickness=0, **kwargs)
        self.vertices, self.faces = [], []
        self.angle_x, self.angle_y = -0.38, 0.45
        self.zoom = 1.0
        self.last = None
        self.caption = 'Выберите зелье слева'
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<ButtonPress-1>', self.start_drag)
        self.bind('<B1-Motion>', self.drag)
        self.bind('<MouseWheel>', self.wheel)
        self.bind('<Button-4>', lambda _: self.change_zoom(1.12))
        self.bind('<Button-5>', lambda _: self.change_zoom(1/1.12))

    def set_mesh(self, vertices=None, faces=None, caption=''):
        self.vertices = vertices or []
        self.faces = faces or []
        self.caption = caption
        self.angle_x, self.angle_y, self.zoom = -0.38, 0.45, 1.0
        self.draw()

    def start_drag(self, ev): self.last = ev.x, ev.y

    def drag(self, ev):
        if not self.last or not self.vertices: return
        dx, dy = ev.x - self.last[0], ev.y - self.last[1]
        self.angle_y += dx * 0.012
        self.angle_x += dy * 0.012
        self.last = ev.x, ev.y
        self.draw()

    def wheel(self, ev): self.change_zoom(1.12 if ev.delta > 0 else 1/1.12)

    def change_zoom(self, factor):
        if not self.vertices: return
        self.zoom = min(15, max(0.12, self.zoom * factor))
        self.draw()

    def draw(self):
        self.delete('all')
        w, h = max(self.winfo_width(), 100), max(self.winfo_height(), 100)
        self.create_text(w/2, 18, text='ПРОСМОТР МОДЕЛИ', fill='#909bab', font=('Arial', 10, 'bold'))
        if not self.vertices:
            self.create_text(w/2, h/2, text=self.caption or 'Модель не найдена', fill='#bdc6d5',
                             font=('Arial', 11), width=max(w-30, 80), justify='center')
            return
        xs, ys, zs = zip(*self.vertices)
        center = ((min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2)
        extent = max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs), 0.001)
        scale = min(w, h) * .63 * self.zoom / extent
        cx, sx = math.cos(self.angle_x), math.sin(self.angle_x)
        cy, sy = math.cos(self.angle_y), math.sin(self.angle_y)
        projected = []
        for x,y,z in self.vertices:
            x,y,z = x-center[0], y-center[1], z-center[2]
            x,z = x*cy + z*sy, -x*sy + z*cy
            y,z = y*cx-z*sx, y*sx+z*cx
            projected.append((w/2+x*scale, h/2-y*scale, z))
        triangles = []
        for a,b,c in self.faces:
            p,q,r = projected[a], projected[b], projected[c]
            ux,uy = q[0]-p[0], q[1]-p[1]
            vx,vy = r[0]-p[0], r[1]-p[1]
            area = abs(ux*vy-uy*vx)
            if area < .01: continue
            brightness = int(min(188, max(60, 88 + 95*area/(area+380))))
            triangles.append(((p[2]+q[2]+r[2])/3, (p[0],p[1],q[0],q[1],r[0],r[1]), brightness))
        triangles.sort(key=lambda t: t[0])
        # Huge models are not the target of the potion viewer.
        if len(triangles) > 15000:
            self.create_text(w/2,h/2,text='Слишком сложная модель для простого просмотрщика',fill='white')
            return
        for _, coords, shade in triangles:
            self.create_polygon(*coords, fill=f'#{shade:02x}{min(255,shade+9):02x}{min(255,shade+21):02x}', outline='#354153', width=.4)
        self.create_text(w/2, h-20, text='ЛКМ — вращение     Колесо — масштаб', fill='#94a3b8', font=('Arial', 9))


