"""World resource selection and dialogs; all writes stay in WorldResources."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from gothic_editor.core.world_resources import WorldResources, resource_name
from gothic_editor.core.model_export import export_texture, preview_3ds
from gothic_editor.core.mesh import read_mrm
from gothic_editor.ui.widgets import BG, MUTED, label
from gothic_editor.ui.windows.dialog import EditorDialog


class WorldController:
    def __init__(self, app):
        self.app = app
        self.current = None
        self.catalog_stamp = None
        self.catalog = []

    @property
    def store(self):
        return WorldResources(self.app.repo.root)

    def refresh(self):
        repo = self.app.repo
        stamp = (repo.root, repo.game, repo.resource_revision)
        if stamp != self.catalog_stamp:
            self.catalog = self.store.catalog(repo)
            self.catalog_stamp = stamp
        self.app.npcs.refresh()
        self.app.world_panel.set_resources(self.catalog,self.app.npcs.items)

    def select(self, resource, camera=None):
        app = self.app
        if not app._save_editors():return
        app.npcs.deselect()
        app._cancel_model_load()
        app.current = None
        app.properties.show(None)
        self.current = resource
        app._show_resource_panels('world')
        app.world_properties.show(resource)
        app._show_model_source(resource.source, camera)

    def loaded(self, preview):
        if self.current is not None:self.app.world_properties.show(self.current, preview)

    def _error(self, exc):
        messagebox.showerror('Ресурсы мира', str(exc), parent=self.app)

    def _confirm(self, operation):
        window = EditorDialog(self.app)
        window.title('Замена ресурса')
        window.geometry('480x230')
        label(window, 'Изменение затронет все объекты, использующие этот ресурс.',
              bg=BG, wraplength=430, justify='left').pack(fill='x', padx=20, pady=20)
        label(window, 'Оригинальные файлы Gothic сохраняются.', bg=BG, fg=MUTED,
              wraplength=430).pack(fill='x', padx=20)
        def accept():
            window.destroy()
            try:
                operation()
                self._changed()
            except (OSError, ValueError, UnicodeError) as exc:self._error(exc)
        window.add_button(window, 'Применить', accept).pack(side='right', padx=12, pady=15)
        window.add_button(window, 'Отмена', window.destroy).pack(side='right', pady=15)
        window.show_centered(modal=True)

    def _changed(self):
        name = self.current.name
        self.app.repo.refresh()
        self.refresh()
        self.app.resources.refresh()
        resource = next((value for value in self.catalog if value.name.casefold() == name.casefold()), None)
        if resource is not None:self.select(resource)
        else:
            self.current = None
            self.app._cancel_model_load()
            self.app.world_properties.show(None)
            self.app.viewer.set_mesh(caption='Выберите объект мира')

    def replace_model(self):
        resource = self.current
        if resource is None:return
        source = filedialog.askopenfilename(parent=self.app, title='Заменить модель', filetypes=[('3DS', '*.3ds')])
        if source:self._confirm(lambda:self.store.replace('model', resource.name, source, resource.category))

    def reset_model(self):
        resource = self.current
        if resource is not None:self._confirm(lambda:self.store.remove('model', resource.name))

    def replace_texture(self, name):
        source = filedialog.askopenfilename(parent=self.app, title='Заменить текстуру', filetypes=[('TGA / TEX', '*.tga *.tex')])
        if source:self._confirm(lambda:self.store.replace('texture', name, source))

    def reset_texture(self, name):
        self._confirm(lambda:self.store.remove('texture', name))

    def texture_overridden(self, name):
        return resource_name(name, 'texture').casefold() in self.store.overrides('texture')

    def export_model(self):
        resource = self.current
        if resource is None:return
        destination = filedialog.asksaveasfilename(parent=self.app, initialfile=resource.name,
            defaultextension='.3ds', filetypes=[('3DS', '*.3ds')])
        if not destination:return
        try:
            data = resource.source.read_bytes()
            if Path(resource.source.name).suffix.lower() == '.mrm':data = preview_3ds(read_mrm(data, preview=True))
            Path(destination).write_bytes(data)
        except (OSError, ValueError) as exc:self._error(exc)

    def texture(self, name, operation):
        resource = self.current
        if resource is None:return
        app = self.app
        source = resource.source
        assets = source.parent if isinstance(source, Path) else None
        try:
            key = app._preview_cache.key(source, (app.repo.root, app.repo.resource_revision), True, assets)
            future = app._model_executor.submit(app._preview_cache.load, key, source, app.repo.root,
                app.repo.game, assets, dict(app.repo.archive_models.texture_entries), with_textures=True)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return
        def finish():
            if self.current is not resource:return
            if not future.done():
                app.after(30, finish)
                return
            try:
                preview = future.result()
                texture = preview.textures.get(name)
                if texture is None:raise ValueError('Текстура не найдена: ' + name)
                if operation == 'export':
                    destination = filedialog.asksaveasfilename(parent=app,
                        initialfile=resource_name(name, 'texture'), defaultextension='.tga', filetypes=[('TGA', '*.tga')])
                    if destination:export_texture(texture, preview.texture_sources.get(name), destination)
                else:
                    window = EditorDialog(app)
                    window.title(name)
                    window.geometry('480x360')
                    # Use the existing mipmaps and native Tk image for a bounded preview.
                    level = next((level for level in texture.mipmaps if max(level.width, level.height) <= 300), texture.mipmaps[-1])
                    rgb = bytes(channel for i, channel in enumerate(level.pixels) if i % 4 != 3)
                    picture = tk.PhotoImage(master=window,
                        data=f'P6\n{level.width} {level.height}\n255\n'.encode() + rgb, format='PPM')
                    image = label(window, '', bg=BG)
                    image.config(image=picture)
                    image.image = picture
                    image.pack(fill='both', expand=True, padx=12, pady=12)
                    window.show_centered()
            except (OSError, ValueError) as exc:self._error(exc)
        app.after(30, finish)
