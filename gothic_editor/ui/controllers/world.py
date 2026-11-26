"""World resource selection and dialogs; all writes stay in WorldResources."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from gothic_editor.core.world_resources import WorldResources, resource_name
from gothic_editor.core.model_export import export_texture, preview_3ds
from gothic_editor.core.mesh import read_mrm
from gothic_editor.ui.widgets import BG, MUTED, label
from gothic_editor.ui.windows.dialog import EditorDialog
from gothic_editor.core.project_selection import ProjectSelection
from gothic_editor.ui.windows.value_choice import ValueChoiceWindow


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
        selected=ProjectSelection(repo.root,'Worlds').read()
        self.app.world_panel.set_resources([value for value in self.catalog if value.overridden or value.name.casefold() in selected])

    def _resource_paths(self,kind,name):
        store=self.store
        logical=resource_name(name,kind)
        path=store._target(logical,kind)
        paths=[store.manifest,path]
        if kind=='model':paths.append(path.with_suffix('.mrm'))
        existing=store.overrides(kind).get(logical.casefold())
        if existing is not None:paths.append(existing)
        return paths

    def _remember(self,paths,operation):
        saved=self.app.history.capture(paths)
        result=operation()
        self.app.history.record(saved)
        return result

    def open_world_preview(self):
        """Open a separate read-only .ZEN viewer; leave model selection intact."""
        from gothic_editor.ui.windows.world_preview import WorldPreviewWindow
        WorldPreviewWindow(self.app, self.app.repo.game)

    def add(self):
        self.refresh()
        options=self.catalog
        def choose(index):
            resource=options[index]
            selection=ProjectSelection(self.app.repo.root,'Worlds')
            self._remember((selection.path,),lambda:selection.add(resource.name))
            window.destroy()
            self.app.events.publish('world.changed',('selection',resource))
            self.select(resource)
        window=ValueChoiceWindow(self.app,[(value.title,value.name) for value in options],-1,
                                 'Добавить объект из Gothic',choose,lambda:window.destroy())
        window.show()

    def select(self, resource, camera=None):
        app = self.app
        if not app._save_editors():return False
        app.npcs.deselect()
        app._cancel_model_load()
        app.current = None
        app.properties.show(None)
        self.current = resource
        app._show_resource_panels('world')
        app.world_properties.show(resource)
        app._show_model_source(resource.source, camera)

    def remove(self):
        resource=self.current
        if resource is None:return
        if not messagebox.askyesno('Удалить из проекта',
                'Удалить объект из списка проекта и отменить замену его модели? '
                'Глобальные замены текстур сохранятся; их можно отменить отдельно.',parent=self.app):return
        try:
            selection=ProjectSelection(self.app.repo.root,'Worlds')
            paths=[*self._resource_paths('model',resource.name),selection.path]
            def remove():
                self.store.remove('model',resource.name)
                selection.remove(resource.name)
            # Stop the preview before deleting its source (Windows file locks).
            self.app._cancel_model_load()
            self._remember(paths,remove)
            self.current=None
            self.catalog_stamp=None
            self.app.events.publish('world.changed',('model',resource))
            self.app.world_properties.show(None)
            self.app.viewer.set_mesh(caption='Выберите объект мира')
        except (OSError,ValueError) as exc:self._error(exc)

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
        self.app.events.publish('world.changed',('model',self.current))
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
        source = filedialog.askopenfilename(parent=self.app, title='Заменить модель', filetypes=[('Готовая модель Gothic (MRM)', '*.mrm'),('3DS', '*.3ds')])
        if source:self._confirm(lambda:self._remember(self._resource_paths('model',resource.name),
            lambda:self.store.replace('model',resource.name,source,resource.category)))

    def reset_model(self):
        resource = self.current
        if resource is not None:self._confirm(lambda:self._remember(self._resource_paths('model',resource.name),
            lambda:self.store.remove('model',resource.name)))

    def replace_texture(self, name):
        source = filedialog.askopenfilename(parent=self.app, title='Заменить текстуру', filetypes=[('TGA / TEX', '*.tga *.tex')])
        if source:self._confirm(lambda:self._remember(self._resource_paths('texture',name),
            lambda:self.store.replace('texture',name,source)))

    def reset_texture(self, name):
        self._confirm(lambda:self._remember(self._resource_paths('texture',name),
            lambda:self.store.remove('texture',name)))

    def texture_overridden(self, name):
        return resource_name(name, 'texture').casefold() in self.store.overrides('texture')

    def export_model(self):
        resource = self.current
        if resource is None:return
        destination = filedialog.asksaveasfilename(parent=self.app, initialfile=str(Path(resource.name).with_suffix('.3ds')),
            defaultextension='.3ds', filetypes=[('3DS', '*.3ds')])
        if not destination:return
        try:
            data = resource.source.read_bytes()
            if Path(resource.source.name).suffix.lower() == '.mrm':data = preview_3ds(read_mrm(data, preview=True))
            elif Path(resource.source.name).suffix.lower() in ('.mdm','.mdl'):
                from gothic_editor.core.model_preview import load_model_preview
                preview=load_model_preview(resource.source,self.app.repo.root,self.app.repo.game,
                    with_textures=False,animation_entries=self.app.repo.archive_models.animation_entries)
                data=preview_3ds(preview.mesh)
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
                app.repo.game, assets, dict(app.repo.archive_models.texture_entries), with_textures=True,
                animation_entries=dict(app.repo.archive_models.animation_entries))
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
