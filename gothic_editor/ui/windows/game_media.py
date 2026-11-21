"""Editor for project-owned menu/chapter textures and Bink videos."""
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

from gothic_editor.core.game_media import GameMedia
from gothic_editor.core.textures import read_ztex
from gothic_editor.ui.windows.dialog import EditorDialog
from gothic_editor.ui.widgets.theme import BG, PANEL, TXT, MUTED


class GameMediaWindow(EditorDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.title('Медиа Gothic')
        self.geometry('730x540')
        self.store = GameMedia(parent.repo.root)
        self.history = parent.history
        self.kind = tk.StringVar(self, value='images')
        self.name = tk.StringVar(self)
        self._picture = None

        header = tk.Frame(self, bg=BG)
        header.pack(fill='x', padx=12, pady=10)
        for kind, title in (('images', 'Изображения'), ('videos', 'Видео')):
            tk.Radiobutton(header, text=title, value=kind, variable=self.kind,
                           command=self.refresh, bg=BG, fg=TXT, selectcolor=PANEL,
                           activebackground=BG, activeforeground=TXT).pack(side='left', padx=8)

        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=12)
        left = tk.Frame(body, bg=BG)
        left.pack(side='left', fill='y')
        self.entries = tk.Listbox(left, width=30, bg=PANEL, fg=TXT,
                                  selectbackground='#36516c', relief='flat', exportselection=False)
        self.entries.pack(fill='both', expand=True)
        self.entries.bind('<<ListboxSelect>>', self.select)
        right = tk.Frame(body, bg=BG)
        right.pack(side='left', fill='both', expand=True, padx=(12, 0))
        self.preview = tk.Label(right, text='Выберите ресурс', bg=PANEL, fg=MUTED,
                                width=46, height=13, anchor='center', compound='center')
        self.preview.pack(fill='both', expand=True)
        tk.Label(right, text='Имя оригинального ресурса Gothic:', fg=TXT, bg=BG,
                 anchor='w').pack(fill='x', pady=(12, 4))
        self.name_entry = tk.Entry(right, textvariable=self.name, bg=PANEL, fg=TXT,
                                   insertbackground=TXT, relief='flat')
        self.name_entry.pack(fill='x', ipady=6)
        tk.Label(right, text='Быстрый выбор:', fg=MUTED, bg=BG,
                 anchor='w').pack(fill='x', pady=(8, 2))
        presets=tk.Frame(right, bg=BG)
        presets.pack(fill='x')
        for caption, resource in (('Меню', 'STARTSCREEN.TGA'), ('Загрузка', 'LOADING.TGA'),
                                  ('Логотип', 'MENUGOTHIC.TGA')):
            tk.Button(presets, text=caption, command=lambda value=resource:self.name.set(value)
                      ).pack(side='left', padx=(0, 5))
        tk.Label(right, text='Изображения: TGA/TEX → -C.TEX в MOD.\n'
                 'Видео: готовые BIK → отдельная папка dist/Video.\n'
                 'Имена должны совпадать с оригинальными ресурсами Gothic.',
                 bg=BG, fg=MUTED, justify='left', anchor='w').pack(fill='x', pady=10)
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill='x', padx=12, pady=12)
        tk.Button(footer, text='Импортировать / заменить', command=self.import_file).pack(side='left', padx=4)
        tk.Button(footer, text='Удалить', command=self.delete).pack(side='left', padx=4)
        tk.Button(footer, text='Обновить', command=self.refresh).pack(side='left', padx=4)
        tk.Button(footer, text='Закрыть', command=self.destroy).pack(side='right', padx=4)
        self.refresh()

    def refresh(self):
        kind = self.kind.get()
        self._paths = self.store.entries(kind)
        self.entries.delete(0, 'end')
        for path in self._paths:self.entries.insert('end', path.name)
        self.name.set('')
        self._picture = None
        self.preview.configure(image='', text='Выберите ресурс')

    def select(self, _event=None):
        selection = self.entries.curselection()
        if not selection:return
        path = self._paths[selection[0]]
        self.name.set(path.name)
        if self.kind.get() == 'videos':
            self._picture = None
            self.preview.configure(image='', text=f'{path.name}\nВидео BIK\n'
                                   f'{path.stat().st_size // 1024:,} КБ')
            return
        try:
            texture = read_ztex(path.read_bytes())
            factor = max(1, (max(texture.width, texture.height) + 359) // 360)
            width = (texture.width + factor - 1) // factor
            height = (texture.height + factor - 1) // factor
            pixels = texture.pixels
            rgb = bytearray()
            for y in range(0, texture.height, factor):
                for x in range(0, texture.width, factor):
                    offset = (y * texture.width + x) * 4
                    rgb.extend(pixels[offset:offset+3])
            ppm = f'P6\n{width} {height}\n255\n'.encode('ascii') + rgb
            self._picture = tk.PhotoImage(master=self, data=ppm, format='PPM')
            self.preview.configure(image=self._picture, text='')
        except (OSError, ValueError, tk.TclError) as exc:
            self._picture = None
            self.preview.configure(image='', text=f'Не удалось открыть изображение:\n{exc}')

    def import_file(self):
        kind = self.kind.get()
        filters = [('Gothic TGA / TEX', '*.tga *.tex')] if kind == 'images' else [('Bink Video', '*.bik')]
        source = filedialog.askopenfilename(parent=self, title='Выберите медиафайл', filetypes=filters)
        if not source:return
        name = self.name.get().strip() or Path(source).name
        try:
            target = self.store.path(kind, name)
            if target.exists() and not messagebox.askyesno('Заменить',
                    f'Заменить {target.name}?', parent=self):return
            before = self.history.capture((target,)) if kind == 'images' else None
            result = self.store.import_file(kind, name, source)
            if before is not None:self.history.record(before)
            self.refresh()
            index = self._paths.index(result)
            self.entries.selection_set(index)
            self.entries.see(index)
            self.select()
        except (OSError, ValueError) as exc:
            messagebox.showerror('Медиа Gothic', str(exc), parent=self)

    def delete(self):
        selection = self.entries.curselection()
        if not selection:return
        path = self._paths[selection[0]]
        if not messagebox.askyesno('Удалить медиа', f'Удалить {path.name} из проекта?', parent=self):
            return
        try:
            before = self.history.capture((path,)) if self.kind.get() == 'images' else None
            self.store.delete(self.kind.get(), path.name)
            if before is not None:self.history.record(before)
            self.refresh()
        except (OSError, ValueError) as exc:
            messagebox.showerror('Медиа Gothic', str(exc), parent=self)
