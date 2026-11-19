"""Model controls within the schema's appearance group; persistence stays in core."""
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox
from pathlib import Path

from gothic_editor.core.item_assets import ItemAssetManager
from gothic_editor.core.categories import classify
from gothic_editor.core.model_library import ModelLibrary
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets.buttons import PropertyButton
from gothic_editor.ui.widgets.theme import BORDER, FIELD_FONT
from gothic_editor.ui.widgets.inputs import make_entry
from gothic_editor.ui.widgets.choice_field import ExpressionChoiceField
from gothic_editor.ui.windows.dialog import EditorDialog


class ItemAppearanceController:
    def __init__(self, app):
        self.app = app

    def show(self, parent, item):
        height = tkfont.Font(root=parent, font=FIELD_FONT).metrics('linespace') + 15
        buttons = []
        for key, action in [('choose_model', self.choose), ('import_model', self.import_model),
                            ('import_textures', self.import_textures), ('remove_model', self.remove)]:
            if classify(item)!='potions' and key!='choose_model':continue
            title = tr('item_assets.' + key)
            button = PropertyButton(parent, lambda fn=action: fn(self.app.current or item), text=title,
                                    height=height, background=BORDER)
            if key == 'remove_model' and not self._custom(item):button.config(state='disabled')
            buttons.append(button)
        width = max(button.winfo_reqwidth() for button in buttons)
        for button in buttons:
            button.configure(width=width)
            button.pack(padx=8, pady=2)

    def _custom(self, item):
        return item.visual.casefold() in ModelLibrary(self.app.repo.root).index()

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
            if not self.app.properties.save(automatic=True):return
            item=next((current for current in self.app.repo.items
                       if current.instance.casefold()==item.instance.casefold()),item)
            item = self._component(item)
            operation(item, ItemAssetManager(self.app.repo.root))
            self.app.repo.refresh()
            updated = next(current for current in self.app.repo.project_items
                           if current.instance.casefold() == item.instance.casefold())
            self.app.update_hierarchy()
            self.app.hierarchy.choose(updated)
            self.app.select(updated)
            self.app.resources.refresh()
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

    def model_options(self):
        repo = self.app.repo
        library=ModelLibrary(repo.root).index()
        choices={name:(f'Проект / {path.parent.name}',ModelLibrary.name(path)) for name,path in library.items()}
        for name,path in repo.mesh_index.items():
            if repo.game and repo.game in path.resolve().parents:
                choices.setdefault(name,(f'Gothic / {path.name}',path.name))
        for entry in repo.archive_models.entries.values():
            if repo.game is None or repo.game not in entry.archive.resolve().parents:continue
            name=str(Path(entry.name).with_suffix('.3ds'))
            choices.setdefault(name.casefold(),(f'Gothic / {name}',name))
        return sorted(choices.values(),key=lambda pair:pair[0].casefold())

    def choose(self, item):
        repo=self.app.repo
        options=self.model_options()
        window = EditorDialog(self.app)
        window.title(tr('item_assets.choose_model'))
        window.geometry('480x230')
        query = tk.StringVar(window)
        make_entry(window, textvariable=query, width=45).pack(fill='x', padx=12, pady=12)
        choice = ExpressionChoiceField(window,tuple(options),state='readonly',
                                       caption=tr('item_assets.choose_model'))
        choice.pack(fill='x', padx=12, pady=(0,12))
        if options:
            current=next((value for _,value in options if value.casefold()==item.visual.casefold()),None)
            if current is not None:choice.set_expression(current)
            else:choice.current(0)

        def filter_names(*_):
            matches = [pair for pair in options if query.get().casefold() in pair[0].casefold()]
            choice.options=tuple(matches)
            choice.set_expression(matches[0][1] if matches else '')
        query.trace_add('write', filter_names)

        def select():
            value = choice.get()
            if not value or not self._confirm_replace(item):return
            window.destroy()
            if classify(item)!='potions':
                self.app.save_fields(item, {'visual':'"' + value.replace('\\','\\\\').replace('"','\\"') + '"'})
                return
            def operation(current, manager):
                repo.edit(current, {'visual':'"' + value.replace('\\','\\\\').replace('"','\\"') + '"'})
            self._run(item, operation)
        window.add_button(window,tr('settings.choose'),select).pack(fill='x',padx=12,pady=(0,12))
        window.bind('<Escape>',lambda _:window.destroy())
        window.show_centered(modal=True)
