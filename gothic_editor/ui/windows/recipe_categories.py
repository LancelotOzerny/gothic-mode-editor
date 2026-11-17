"""Edit category titles and custom menu groups using shared form widgets."""
from tkinter import messagebox
from gothic_editor.core.recipe_categories import RecipeCategories, STOCK
from gothic_editor.core.recipes import RecipeStore
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets.panel import ScrollableArea
from gothic_editor.ui.widgets.form import FormGroup
from .dialog import EditorDialog


class RecipeCategoryDialog(EditorDialog):
    def __init__(self, owner, store, on_saved, category=None):
        super().__init__(owner)
        self.store, self.on_saved, self.category = store, on_saved, category
        self.title(tr('recipes.edit_category' if category else 'recipes.add_category'))
        self.geometry('420x310')
        group = FormGroup(self, tr('recipes.category'))
        group.pack(fill='both', expand=True, padx=12, pady=12)
        self.code = group.add_field(tr('recipes.id'), value=category['id'] if category else '')
        self.name = group.add_field(tr('recipes.name'), value=category['name'] if category else '')
        group.add_button(tr('settings.save'), self.save)
        group.add_button(tr('settings.cancel'), self.destroy)
        self.bind('<Escape>', lambda _:self.destroy())

    def save(self):
        try:
            self.store.change(self.category['id'] if self.category else None,
                              {'id':self.code.get(), 'name':self.name.get()})
        except (OSError, ValueError) as exc:
            messagebox.showerror(tr('recipes.category'), str(exc), parent=self)
            return
        self.destroy()
        self.on_saved()


class RecipeCategoriesWindow(EditorDialog):
    def __init__(self, owner, project, on_saved):
        super().__init__(owner)
        self.title(tr('recipes.categories'))
        self.geometry('540x600')
        self.store = RecipeCategories(project)
        self.project, self.on_saved = project, on_saved
        self.rows = []
        self.add_button(self, tr('settings.save'), self.save).pack(side='bottom', fill='x')
        self.add_button(self, tr('recipes.add_category'), self.add).pack(side='bottom', fill='x')
        self.area = ScrollableArea(self)
        self.area.pack(fill='both', expand=True)
        for row in self.store.load():self.add(row)

    def add(self, data=None):
        data = data or {'id': '', 'name': ''}
        group = FormGroup(self.area.content, tr('recipes.category'))
        group.pack(fill='x')
        code = group.add_field(tr('recipes.id'), value=data['id'], readonly=data['id'] in STOCK)
        name = group.add_field(tr('recipes.name'), value=data['name'])
        row = (group, code, name)
        self.rows.append(row)
        if data['id'] not in STOCK:
            def remove():
                self.rows.remove(row)
                group.destroy()
            group.add_button(tr('recipes.delete'), remove)

    def save(self):
        try:
            rows = [{'id': code.get(), 'name': name.get()} for _, code, name in self.rows]
            keys = {row['id'] for row in rows}
            for recipe in RecipeStore(self.project).load():
                if recipe.get('category') and recipe['category'] not in keys:
                    raise ValueError(f'{recipe["id"]}: сначала перенесите рецепт в другую категорию.')
            self.store.save(rows)
            self.destroy()
            self.on_saved()
        except (OSError, ValueError) as exc:messagebox.showerror(tr('recipes.categories'), str(exc), parent=self)
