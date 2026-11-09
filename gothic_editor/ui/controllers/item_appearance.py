"""Model controls within the schema's appearance group; persistence stays in core."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from gothic_editor.core.item_assets import ItemAssetManager
from gothic_editor.core.categories import classify
from gothic_editor.core.model_resolver import ModelResolver
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets.buttons import PropertyButton


class ItemAppearanceController:
    def __init__(self, app):
        self.app = app

    def show(self, parent, item):
        for key, action in [('choose_model', self.choose), ('import_model', self.import_model),
                            ('import_textures', self.import_textures), ('remove_model', self.remove)]:
            if classify(item)!='potions' and key!='choose_model':continue
            button = PropertyButton(parent,lambda fn=action:fn(self.app.current or item),text=tr('item_assets.'+key))
            button.pack(fill='x', padx=8, pady=(0,6))
            if key == 'remove_model' and not self._custom(item):button.config(state='disabled')

    def _custom(self, item):
        return self.app.repo.components.owns(item.path) and ModelResolver.custom_model(item.path.parent).is_file()

    def _confirm_replace(self, item):
        return not self._custom(item) or messagebox.askyesno(tr('item_assets.appearance'),
            tr('item_assets.replace_confirm'), parent=self.app)

    def _component(self, item):
        repo = self.app.repo
        if not repo.components.owns(item.path):
            item = repo.copy_to_project(item) if item.origin == 'game' else repo.edit(item, {}, metadata={})
        return item

    def _run(self, item, operation):
        try:
            item = self._component(item)
            operation(item, ItemAssetManager(self.app.repo.root))
            self.app.repo.refresh()
            updated = next(current for current in self.app.repo.project_items
                           if current.instance.casefold() == item.instance.casefold())
            self.app.update_hierarchy()
            self.app.hierarchy.choose(updated)
            self.app.select(updated)
        except (OSError, ValueError) as exc:
            messagebox.showerror(tr('item_assets.appearance'), str(exc), parent=self.app)

    def import_model(self, item):
        source = filedialog.askopenfilename(parent=self.app, title=tr('item_assets.import_model'),
                                           filetypes=[('3D Studio (*.3ds)', '*.3ds')])
        if not source or not self._confirm_replace(item):return
        self._run(item, lambda current, manager:manager.import_model(current, Path(source)))

    def import_textures(self, item):
        sources = filedialog.askopenfilenames(parent=self.app, title=tr('item_assets.import_textures'),
                                             filetypes=[('Gothic textures', '*.tga *.tex')])
        if sources:self._run(item, lambda current, manager:manager.import_textures(current, sources))

    def remove(self, item):
        if self._confirm_replace(item):
            self._run(item, lambda current, manager:manager.remove_model(current))

    def choose(self, item):
        repo = self.app.repo
        custom = {ModelResolver.generated_name(current.instance).casefold() for current in repo.project_items}
        names = {path.name for path in repo.mesh_index.values() if path.name.casefold() != 'model.3ds'}
        names.update(str(Path(entry.name).with_suffix('.3ds')) for entry in repo.archive_models.entries.values())
        names = sorted((name for name in names if name.casefold() not in custom), key=str.casefold)
        window = tk.Toplevel(self.app)
        window.title(tr('item_assets.choose_model'))
        window.transient(self.app)
        query = tk.StringVar(window)
        ttk.Entry(window, textvariable=query, width=45).pack(fill='x', padx=12, pady=12)
        choice = ttk.Combobox(window, values=names, state='readonly', width=45)
        choice.pack(fill='x', padx=12, pady=(0,12))
        if names:choice.current(0)

        def filter_names(*_):
            matches = [name for name in names if query.get().casefold() in name.casefold()]
            choice.config(values=matches)
            choice.set(matches[0] if matches else '')
        query.trace_add('write', filter_names)

        def select():
            value = choice.get()
            if not value or not self._confirm_replace(item):return
            window.destroy()
            if classify(item)!='potions':
                self.app.save_fields(item, {'visual':'"' + value.replace('\\','\\\\').replace('"','\\"') + '"'})
                return
            def operation(current, manager):
                if self._custom(current):manager.remove_model(current)
                repo.edit(current, {'visual':'"' + value.replace('\\','\\\\').replace('"','\\"') + '"'})
            self._run(item, operation)
        ttk.Button(window, text=tr('settings.choose'), command=select).pack(pady=(0,12))
        window.grab_set()
