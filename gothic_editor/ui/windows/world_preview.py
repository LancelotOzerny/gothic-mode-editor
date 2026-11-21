"""Separate, read-only wireframe viewer for Gothic .ZEN worlds."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import traceback
import tkinter as tk
from tkinter import filedialog

from gothic_editor.core.world_preview import (load_world_wireframe, project_wireframe,
    available_locations, is_location_zen)


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
        self.canvas.bind('<ButtonPress-3>', lambda event: self.begin_drag(event, 'pan'))
        self.canvas.bind('<B3-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-3>', self.end_drag)
        self.canvas.bind('<MouseWheel>', lambda event: self.change_zoom(1.12 if event.delta > 0 else 1/1.12))
        self.canvas.bind('<Button-4>', lambda event: self.change_zoom(1.12))
        self.canvas.bind('<Button-5>', lambda event: self.change_zoom(1/1.12))
        footer = tk.Label(self, text='ЛКМ — вращение  ·  ПКМ — сдвиг  ·  Колесо — масштаб  ·  Без текстур и VOB-моделей',
                          bg='#232b39', fg='#94a3b8', anchor='center')
        footer.pack(fill='x', pady=0, ipady=7)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_locations()
        self.queue_draw()

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
        self._reported_draw_error = None
        self.queue_draw()
        self._loading_source = str(path.archive / path.name) if hasattr(path, 'archive') else str(path)
        self._future = self._executor.submit(load_world_wireframe, path)
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
            self._scene = future.result()
        except Exception as exc:
            self.status.configure(text='Ошибка чтения ZEN: ' + str(exc))
            self._log_exception('Ошибка загрузки', exc)
        else:
            self.reset_camera()
            self.status.configure(text=(f'Вершин: {self._scene.total_vertices:,}  ·  '
                f'Треугольников: {self._scene.total_triangles:,}  ·  '
                f'Показано: {len(self._scene.faces):,}'))
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

    def reset_camera(self):
        self.yaw, self.pitch, self.zoom = 0.55, -0.45, 1.0
        self.pan_x = self.pan_y = 0.0
        self.queue_draw()

    def begin_drag(self, event, mode):
        self._drag = (event.x, event.y)
        self._drag_mode = mode

    def end_drag(self, event):
        self._drag = None
        self._drag_mode = None

    def drag(self, event):
        if self._drag is None or self._scene is None:
            return
        dx, dy = event.x - self._drag[0], event.y - self._drag[1]
        self._drag = (event.x, event.y)
        if self._drag_mode == 'rotate':
            self.yaw += dx * 0.008
            self.pitch = max(-1.5, min(1.5, self.pitch + dy * 0.008))
        else:
            self.pan_x += dx
            self.pan_y += dy
        self.queue_draw()

    def change_zoom(self, factor):
        if self._scene is None:
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
            self.canvas.create_text(w/2, h/2, text='Геометрия мира пуста',
                fill='#94a3b8', tags='scene')
            return
        try:
            points = project_wireframe(scene, w, h, self.yaw, self.pitch,
                                       self.zoom, self.pan_x, self.pan_y)
            # Draw back-to-front so near edges remain legible.
            faces = sorted(scene.faces, key=lambda f: sum(points[i][2] for i in f))
            for a, b, c in faces:
                triangle = (points[a], points[b], points[c])
                if all(p[0] < -10 for p in triangle) or all(p[0] > w+10 for p in triangle):
                    continue
                if all(p[1] < -10 for p in triangle) or all(p[1] > h+10 for p in triangle):
                    continue
                coords = [coordinate for p in triangle for coordinate in p[:2]]
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
        for callback in (self._draw_id, self._poll_id):
            if callback is not None:
                self.after_cancel(callback)
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()
