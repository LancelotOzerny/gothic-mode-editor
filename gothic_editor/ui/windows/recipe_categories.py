"""Edit category titles and custom menu groups using shared form widgets."""
from tkinter import messagebox
from gothic_editor.core.recipe_categories import RecipeCategories, STOCK
from gothic_editor.core.recipes import RecipeStore
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets.panel import ScrollableArea
from gothic_editor.ui.widgets.form import FormGroup
from .dialog import EditorDialog


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
