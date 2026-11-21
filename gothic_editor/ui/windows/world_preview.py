"""Separate, read-only wireframe viewer for Gothic .ZEN worlds."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import traceback
from math import isfinite
from time import monotonic
from gothic_editor.core.fly_camera import FlyCamera
import tkinter as tk
from tkinter import filedialog

from gothic_editor.core.world_preview import (load_world_wireframe, project_wireframe,
    available_locations, is_location_zen, face_color, camera_chunk,
    move_camera, drag_camera)


class WorldPreviewWindow(tk.Toplevel):
    def __init__(self, parent, game=None):
        super().__init__(parent)
        self.title('Редактор локаций Gothic — просмотр геометрии')
        self.geometry('1020x710')
        self.configure(bg='#191e29')
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._future = None
        self._poll_id = None
        self._draw_id = None
        self._scene = None
        self._world = None
        self._focus = None
        self._pressed.clear()
        self._camera_center = None
        self._camera_target = None
        self._world_height = 0.0
        self._animation_id = None
        self._solid = True
        self._fly_mode = True
        self._fly_camera = FlyCamera()
        self._pressed = set()
        self._tick_id = None
        self._last_tick = monotonic()
        self._fly_mouse = None
        settings = getattr(parent, 'settings', None)
        self._chunk_size = settings.get_value('interface.world_chunks.size') if settings else 6000
        self._chunk_radius = settings.get_value('interface.world_chunks.radius') if settings else 1
        self._triangle_limit = settings.get_value('interface.world_chunks.triangle_limit') if settings else 3500
        self._closed = False
        self._drag = None
        self._drag_mode = None
        self.yaw = 0.55
        self.pitch = -0.45
        self.zoom = 1.0
        self.pan_x = self.pan_y = 0.0
        self._game = Path(game) if game else None
        self._reported_draw_error = None
        self._location_paths = []
        header = tk.Frame(self, bg='#232b39')
        header.pack(fill='x')
        tk.Button(header, text='Открыть файл .ZEN', command=self.choose_file,
                  bg='#334155', fg='white', relief='flat').pack(side='left', padx=12, pady=10)
        tk.Label(header, text='Локация:', bg='#232b39',
                 fg='#cbd5e1').pack(side='left', padx=(14, 4))
        self.location_value = tk.StringVar(self)
        self.location_menu = tk.OptionMenu(header, self.location_value, '')
        self.location_menu.configure(bg='#334155', fg='white', relief='flat',
                                     highlightthickness=0, width=24)
        self.location_menu.pack(side='left', padx=4)
        self.location_value.trace_add('write', self._selected_location)
        tk.Button(header, text='Обновить список', command=self.refresh_locations,
                  bg='#334155', fg='white', relief='flat').pack(side='left', padx=4)
        tk.Button(header, text='◀ Участок', command=lambda: self.move_focus(-1, 0),
                  bg='#334155', fg='white', relief='flat').pack(side='left', padx=2)
        tk.Button(header, text='Участок ▶', command=lambda: self.move_focus(1, 0),
                  bg='#334155', fg='white', relief='flat').pack(side='left', padx=2)
        tk.Button(header, text='▲', command=lambda: self.move_focus(0, -1),
                  bg='#334155', fg='white', relief='flat').pack(side='left', padx=2)
        tk.Button(header, text='▼', command=lambda: self.move_focus(0, 1),
                  bg='#334155', fg='white', relief='flat').pack(side='left', padx=2)
        self.surface_button = tk.Button(header, text='Поверхности', command=self.toggle_surfaces,
                  bg='#334155', fg='white', relief='flat')
        self.surface_button.pack(side='left', padx=4)
        self.camera_button = tk.Button(header, text='Камера: полёт', command=self.toggle_camera,
                  bg='#334155', fg='white', relief='flat')
        self.camera_button.pack(side='left', padx=4)
        tk.Button(header, text='Сбросить камеру', command=self.reset_camera,
                  bg='#334155', fg='white', relief='flat').pack(side='left', padx=4)
        self.status = tk.Label(header, text='Выберите файл .ZEN из папки Gothic',
                               bg='#232b39', fg='#cbd5e1', anchor='w')
        self.status.pack(side='left', fill='x', expand=True, padx=14)
        self.canvas = tk.Canvas(self, bg='#191e29', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.queue_draw())
        self.canvas.bind('<ButtonPress-1>', lambda event: self.begin_drag(event, 'rotate'))
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.end_drag)
        self.canvas.bind('<ButtonPress-3>', self.right_press)
        self.canvas.bind('<B3-Motion>', self.right_motion)
        self.canvas.bind('<ButtonRelease-3>', self.right_release)
        self.canvas.bind('<MouseWheel>', lambda event: self.change_zoom(1.12 if event.delta > 0 else 1/1.12))
        self.canvas.bind('<Button-4>', lambda event: self.change_zoom(1.12))
        self.canvas.bind('<Button-5>', lambda event: self.change_zoom(1/1.12))
        self.bind('<KeyPress>', self._key_down, add='+')
        self.bind('<KeyRelease>', self._key_up, add='+')
        self.bind('<FocusOut>', self._clear_keys, add='+')
        self.bind('<FocusIn>', lambda event: self.canvas.focus_set())
        self.canvas.configure(takefocus=True)
        self.canvas.bind('<Button-1>', lambda event: self.canvas.focus_set(), add='+')
        footer = tk.Label(self, text='Полёт: WASD — движение  ·  ПКМ — взгляд  ·  Q/E — вниз/вверх  ·  Shift — ускорение  ·  Home — сброс  ·  колесо — скорость',
                          bg='#232b39', fg='#94a3b8', anchor='center')
        footer.pack(fill='x', pady=0, ipady=7)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_locations()
        self.queue_draw()
        self._tick_id = self.after(33, self._tick)

    def refresh_locations(self):
        self._location_paths = available_locations(self._game) if self._game else []
        menu = self.location_menu['menu']
        menu.delete(0, 'end')
        for index, path in enumerate(self._location_paths):
            label = Path(path.name).stem + (f' [{path.archive.name}]' if hasattr(path, 'archive') else '')
            menu.add_command(label=label, command=lambda i=index: self._load_selection(i))
        if self._location_paths:
            self.status.configure(text=f'Найдено локаций: {len(self._location_paths)}. Выберите мир.')
        else:
            self.status.configure(text='В папке Gothic не найдены игровые .ZEN. Выберите файл вручную.')

    def _load_selection(self, index):
        path = self._location_paths[index]
        self.location_value.set(Path(path.name).stem)
        self.open_file(path)

    def _selected_location(self, *_):
        # Explicit menu action triggers loading; the trace is reserved for future state.
        pass

    def choose_file(self):
        options = {}
        if self._game:
            folder = self._game / '_work' / 'data' / 'Worlds'
            options['initialdir'] = str(folder if folder.is_dir() else self._game)
        path = filedialog.askopenfilename(parent=self, title='Открыть мир Gothic',
            filetypes=[('Миры Gothic', '*.zen *.ZEN'), ('Все файлы', '*.*')], **options)
        if path:
            self.open_file(path)

    def open_file(self, path):
        if not is_location_zen(path):
            self.status.configure(text='Служебный ZEN (пресеты Gothic), не игровая локация: ' + Path(path.name).name)
            self._scene = None
            self.queue_draw()
            return
        if self._future is not None:
            self.status.configure(text='Завершите загрузку текущего мира перед открытием другого.')
            return
        self.status.configure(text='Чтение геометрии: ' + Path(path.name).name)
        self._scene = None
        self._world = None
        self._focus = None
        self._camera_center = None
        self._camera_target = None
        self._world_height = 0.0
        if self._animation_id is not None:
            self.after_cancel(self._animation_id)
            self._animation_id = None
        self._reported_draw_error = None
        self.queue_draw()
        self._loading_source = str(path.archive / path.name) if hasattr(path, 'archive') else str(path)
        self._future = self._executor.submit(load_world_wireframe, path, self._chunk_size)
        self._poll_id = self.after(50, self._poll)

    def _log_message(self, message, *, error=False):
        """Write to the main Gothic Editor bottom terminal, on the Tk thread."""
        app = self.master
        terminal = getattr(app, 'terminal', None)
        if terminal is None:
            return
        terminal.append(message)
        if error and hasattr(app, 'show_terminal'):
            app.show_terminal()

    def _log_exception(self, phase, exc):
        detail = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        source = getattr(self, '_loading_source', '(файл не выбран)')
        self._log_message(f'[ZEN] {phase}: {source}\n{detail}', error=True)

    def _poll(self):
        self._poll_id = None
        if self._closed:
            return
        if not self._future.done():
            self._poll_id = self.after(50, self._poll)
            return
        future, self._future = self._future, None
        try:
            self._world = future.result()
            self._focus = self._world.origin
            self._scene = self._world.view(self._focus, self._chunk_radius,
                                           self._triangle_limit)
            if self._scene.vertices:
                ys = [v[1] for v in self._scene.vertices]
                self._world_height = (min(ys) + max(ys)) / 2
            self._camera_center = self._chunk_center(self._focus)
            self._camera_target = self._camera_center
            self._reset_fly()
        except Exception as exc:
            self.status.configure(text='Ошибка чтения ZEN: ' + str(exc))
            self._log_exception('Ошибка загрузки', exc)
        else:
            self.reset_camera()
            self._update_chunk_status()
            if self._scene.vertices:
                lows = tuple(min(vertex[axis] for vertex in self._scene.vertices)
                             for axis in range(3))
                highs = tuple(max(vertex[axis] for vertex in self._scene.vertices)
                              for axis in range(3))
                extent = max(high - low for low, high in zip(lows, highs))
                if not isfinite(extent) or extent < 1e-6:
                    self._log_message(
                        f'[ZEN] Подозрительная геометрия {self._loading_source}: '
                        f'границы={tuple(zip(lows, highs))}, размер={extent!r}. '
                        'Возможна ошибка декодирования MSH — каркас может быть невидим.',
                        error=True)
            skipped = self._scene.discarded_triangles
            if skipped:
                self._log_message(
                    f'[ZEN] {self._loading_source}: пропущено {skipped:,} '
                    'треугольников с некорректными координатами или индексами.',
                    error=True)
            if not self._scene.faces:
                self.status.configure(text='В ZEN нет пригодных для показа треугольников. Подробности в терминале.')
                self._log_message(
                    f'[ZEN] Нет пригодной геометрии: {self._loading_source}. '
                    'Проверьте формат и правильность чтения MSH.',
                    error=True)
        self.queue_draw()

    def _reset_fly(self):
        if self._camera_center is None:
            return
        x, y, z = self._camera_center
        self._fly_camera = FlyCamera(x=x, y=y + self._world.chunk_size * 0.35,
                                     z=z - self._world.chunk_size,
                                     speed=self._world.chunk_size * 0.8)

    def toggle_camera(self):
        self._fly_mode = not self._fly_mode
        self._pressed.clear()
        self._fly_mouse = None
        self.camera_button.config(
            text='Камера: полёт' if self._fly_mode else 'Камера: обзор')
        if self._fly_mode and self._world is not None:
            self._reset_fly()
        self.queue_draw()

    def _key_down(self, event):
        key = event.keysym.lower()
        if key == 'home':
            self.reset_camera()
            return
        if key in ('w', 'a', 's', 'd', 'q', 'e', 'shift_l', 'shift_r'):
            self._pressed.add(key)
            # Do not leak navigation keys into other widgets.
            return 'break'

    def _key_up(self, event):
        key = event.keysym.lower()
        self._pressed.discard(key)
        if key in ('w', 'a', 's', 'd', 'q', 'e', 'shift_l', 'shift_r'):
            return 'break'

    def _clear_keys(self, event=None):
        self._pressed.clear()
        self._fly_mouse = None

    def right_press(self, event):
        self.canvas.focus_set()
        if self._fly_mode:
            self._fly_mouse = (event.x, event.y)
        else:
            self.begin_drag(event, 'pan')

    def right_motion(self, event):
        if self._fly_mode:
            if self._fly_mouse is None:
                return
            dx, dy = event.x - self._fly_mouse[0], event.y - self._fly_mouse[1]
            self._fly_mouse = (event.x, event.y)
            self._fly_camera.look(dx, dy)
            self.queue_draw()
        else:
            self.drag(event)

    def right_release(self, event):
        self._fly_mouse = None
        self.end_drag(event)

    def _tick(self):
        self._tick_id = None
        if self._closed:
            return
        now = monotonic()
        dt = min(now - self._last_tick, 0.1)
        self._last_tick = now
        if self._fly_mode and self._world is not None:
            keys = self._pressed
            forward = int('w' in keys) - int('s' in keys)
            strafe = int('d' in keys) - int('a' in keys)
            vertical = int('e' in keys) - int('q' in keys)
            if forward or strafe or vertical:
                self._fly_camera.move(
                    forward, strafe, vertical, dt,
                    fast='shift_l' in keys or 'shift_r' in keys)
                self._refresh_fly_chunks()
        self._tick_id = self.after(33, self._tick)

    def _refresh_fly_chunks(self):
        if self._world is None:
            return
        chunk = self._fly_camera.chunk_at(self._world.chunk_size)
        if chunk != self._focus:
            self._focus = chunk
            self._scene = self._world.view(chunk, self._chunk_radius,
                                            self._triangle_limit)
            self._update_chunk_status()
        self.queue_draw()

    def _chunk_center(self, focus):
        size = self._world.chunk_size
        return ((focus[0] + 0.5) * size, self._world_height,
                (focus[1] + 0.5) * size)

    def toggle_surfaces(self):
        self._solid = not self._solid
        self.surface_button.config(text='Поверхности' if self._solid else 'Каркас')
        self.queue_draw()

    def _animate_camera(self):
        self._animation_id = None
        if self._closed or self._camera_center is None or self._camera_target is None:
            return
        current = self._camera_center
        target = self._camera_target
        self._camera_center = tuple(a + (b - a)*0.38 for a, b in zip(current, target))
        if max(abs(a-b) for a, b in zip(self._camera_center, target)) < 1:
            self._camera_center = target
        self.queue_draw()
        if self._camera_center != target:
            self._animation_id = self.after(32, self._animate_camera)

    def _update_chunk_status(self):
        if self._world is None or self._scene is None:
            return
        self.status.configure(
            text=f'Чанк {self._focus[0]}, {self._focus[1]} · '
                 f'Видимых полигонов: {len(self._scene.faces):,} · '
                 f'Участков: {len(self._world.chunks)} · '
                 f'Размер: {self._world.chunk_size} см')

    def move_focus(self, dx, dz):
        if self._world is None:
            return
        self._focus = (self._focus[0] + dx, self._focus[1] + dz)
        self._scene = self._world.view(self._focus, self._chunk_radius,
                                       self._triangle_limit)
        self._camera_target = self._chunk_center(self._focus)
        self.pan_x = self.pan_y = 0.0
        if self._animation_id is not None:
            self.after_cancel(self._animation_id)
            self._animation_id = None
        self._animate_camera()
        self._update_chunk_status()

    def _refresh_visible_chunks(self):
        if self._world is None or self._camera_center is None:
            return
        new_focus = camera_chunk(self._camera_center, self._world.chunk_size)
        if new_focus != self._focus:
            self._focus = new_focus
            self._scene = self._world.view(new_focus, self._chunk_radius,
                                            self._triangle_limit)
            self._update_chunk_status()
        self.queue_draw()

    def fly(self, forward, right):
        if self._world is None or self._camera_center is None:
            return
        # A keypress moves only a fraction of a chunk. Repeated keys feel
        # continuous, while crossing boundaries switches chunks automatically.
        step = self._world.chunk_size * 0.12 / max(0.35, self.zoom)
        self._camera_center = move_camera(
            self._camera_center, forward, right, self.yaw, step)
        self._camera_target = self._camera_center
        if self._animation_id is not None:
            self.after_cancel(self._animation_id)
            self._animation_id = None
        self._refresh_visible_chunks()

    def reset_camera(self):
        self.yaw, self.pitch, self.zoom = 0.55, -0.45, 1.0
        self.pan_x = self.pan_y = 0.0
        if self._world is not None:
            self._reset_fly()
            if self._fly_mode:
                self._refresh_fly_chunks()
        self.queue_draw()

    def begin_drag(self, event, mode):
        if self._fly_mode:
            return
        self._drag = (event.x, event.y)
        self._drag_mode = mode

    def end_drag(self, event):
        self._drag = None
        self._drag_mode = None

    def drag(self, event):
        if self._fly_mode or self._drag is None or self._scene is None:
            return
        dx, dy = event.x - self._drag[0], event.y - self._drag[1]
        self._drag = (event.x, event.y)
        if self._drag_mode == 'rotate':
            self.yaw += dx * 0.008
            self.pitch = max(-1.5, min(1.5, self.pitch + dy * 0.008))
        else:
            width = max(2, self.canvas.winfo_width())
            height = max(2, self.canvas.winfo_height())
            self._camera_center = drag_camera(
                self._camera_center, dx, dy, width, height,
                self.yaw, self.pitch, self.zoom,
                self._world.chunk_size * (2*self._chunk_radius+1))
            self._camera_target = self._camera_center
            if self._animation_id is not None:
                self.after_cancel(self._animation_id)
                self._animation_id = None
            self._refresh_visible_chunks()
        self.queue_draw()

    def change_zoom(self, factor):
        if self._scene is None:
            return
        if self._fly_mode:
            self._fly_camera.speed = max(100.0, min(100000.0, self._fly_camera.speed * factor))
            self._update_chunk_status()
            return
        self.zoom = max(0.08, min(35, self.zoom * factor))
        self.queue_draw()

    def queue_draw(self):
        if self._draw_id is None and not self._closed:
            self._draw_id = self.after_idle(self._draw)

    def _draw(self):
        self._draw_id = None
        self.canvas.delete('scene')
        w = max(2, self.canvas.winfo_width())
        h = max(2, self.canvas.winfo_height())
        scene = self._scene
        if scene is None:
            self.canvas.create_text(w/2, h/2, text='Откройте файл мира .ZEN',
                fill='#94a3b8', font=('Arial', 13), tags='scene')
            return
        if not scene.faces:
            self.canvas.create_text(w/2, h/2, text='В выбранных чанках нет геометрии. Перейдите к соседнему участку (WASD)',
                fill='#94a3b8', tags='scene')
            return
        try:
            points = (self._fly_camera.project(scene.vertices, w, h)
                      if self._fly_mode else project_wireframe(
                scene, w, h, self.yaw, self.pitch, self.zoom,
                self.pan_x, self.pan_y, center=self._camera_center,
                span=self._world.chunk_size * (2*self._chunk_radius+1)
                     if self._world is not None else None)
            # Draw back-to-front so near edges remain legible.
            faces = sorted(
                (f for f in scene.faces if all(points[i] is not None for i in f)),
                key=lambda f: sum(points[i][2] for i in f), reverse=self._fly_mode)
            # Keep animation responsive while many Tk polygons are present.
            if self._animation_id is not None and len(faces) > 1200:
                faces = faces[::max(1, len(faces)//1200)]
            for a, b, c in faces:
                triangle = (points[a], points[b], points[c])
                if all(p[0] < -10 for p in triangle) or all(p[0] > w+10 for p in triangle):
                    continue
                if all(p[1] < -10 for p in triangle) or all(p[1] > h+10 for p in triangle):
                    continue
                coords = [coordinate for p in triangle for coordinate in p[:2]]
                if self._solid:
                    fill = face_color(scene.vertices, (a, b, c))
                    self.canvas.create_polygon(*coords, fill=fill, outline='',
                                               tags='scene')
                else:
                    self.canvas.create_polygon(*coords, fill='', outline='#6f8fa8',
                                               width=1, tags='scene')
        except (ValueError, IndexError, OverflowError, tk.TclError) as exc:
            self.canvas.create_text(w/2, h/2, text='Ошибка отображения: ' + str(exc),
                                    fill='#fca5a5', tags='scene')
            signature = (type(exc).__name__, str(exc))
            if signature != self._reported_draw_error:
                self._reported_draw_error = signature
                self._log_exception('Ошибка отображения', exc)

    def close(self):
        self._closed = True
        for callback in (self._draw_id, self._poll_id, self._animation_id, self._tick_id):
            if callback is not None:
                self.after_cancel(callback)
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()
