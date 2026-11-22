"""Own the recipe draft and participate in the application's save barriers."""
import re
from tkinter import messagebox
from copy import deepcopy
from gothic_editor.core.localization import tr
from gothic_editor.core.recipes import RecipeStore, RecipeError, validate_recipe
from gothic_editor.ui.windows.grouped_choice import GroupedChoiceWindow


class RecipeController:
    def __init__(self, app):
        self.app = app
        self.current = None
        self.items = []
        self.error = ''
        self.pending = None
        self.traces = []
        self.persisted = False
        self.store = None
        self.choice = None

    @property
    def panel(self):
        return self.app.recipe_properties

    def load(self):
        self.store = RecipeStore(self.app.repo.root)
        try:
            self.items = self.store.load()
            from gothic_editor.core.recipe_categories import RecipeCategories
            categories = RecipeCategories(self.app.repo.root)
            categories.load()
            for recipe in self.items:categories.validate(recipe)
            self.error = ''
        except (OSError, ValueError) as exc:
            self.items = []
            self.error = str(exc)
        self.app.recipe_list.populate()

    def deselect(self):
        if self.pending is not None:
            self.app.after_cancel(self.pending)
            self.pending = None
        for variable, trace in self.traces:
            variable.trace_remove('write', trace)
        self.traces = []
        if self.choice is not None:
            self.choice.destroy()
            self.choice = None
        self.current = None

    def watch(self, variable):
        self.traces.append((variable, variable.trace_add('write', lambda *_: self.changed())))

    def changed(self):
        if self.pending is not None:
            self.app.after_cancel(self.pending)
        self.panel.status.config(text=tr('recipes.dirty'))
        self.pending = self.app.after(1000, self.save)

    def select(self, recipe, persisted=True):
        same_recipe = self.current is not None and recipe['id'] == self.current['id']
        if not self.app._save_editors():
            return False
        if same_recipe:
            recipe = self.current
        elif persisted:
            recipe = next((item for item in self.items if item['id'] == recipe['id']), recipe)
        self.deselect()
        self.current = deepcopy(recipe)
        self.persisted = persisted
        self.panel.show(self.current)
        self.app.recipe_list.select_category(None)
        from gothic_editor.core.recipe_categories import RecipeCategories
        categories = {row['id']: row for row in RecipeCategories(self.app.repo.root).load()}
        code = self.current.get('category', '')
        while code:
            self.app.recipe_list.expanded[('project', code)] = True
            code = (categories.get(code) or {}).get('parent') or ''
        self.app.recipe_list.populate()

    def save(self):
        if self.pending is not None:
            self.app.after_cancel(self.pending)
            self.pending = None
        if self.current is None:
            return True
        self.panel.clear_errors()
        try:
            data = deepcopy(self.current)
            data.update({key: field.get() for key, field in self.panel.fields.items()
                         if key not in ('availability', 'variable')})
            def number(value, field):
                if not re.fullmatch(r'[0-9]+', value):
                    raise RecipeError(field, 'Нужно положительное целое число.')
                return int(value)
            data['result_count'] = number(data['result_count'], 'result_count')
            data['ingredients'] = [{'instance': instance.get(), 'count': number(count.get(), 'ingredients')}
                                   for _, instance, count in self.panel.rows if instance.get().strip()]
            data['availability'] = {'type': self.panel.fields['availability'].get()}
            if data['availability']['type'] == 'global_variable':
                data['availability']['variable'] = self.panel.fields['variable'].get()
            validate_recipe(data)
            if data == self.current and self.persisted:
                return True
            old = self.current['id'] if self.persisted else None
            paths=[self.store.path(data['id'])]
            if old and old!=data['id']:paths.append(self.store.path(old))
            saved=self.app.history.capture(paths)
            self.store.save(data, old)
            self.app.history.record(saved)
            self.current = data
            self.persisted = True
            self.items = self.store.load()
            self.app.recipe_list.populate()
            self.panel.status.config(text=tr('recipes.saved'))
            return True
        except (OSError, ValueError) as exc:
            field = self.panel.errors.get(getattr(exc, 'field', ''))
            if field is not None:
                field.config(text=str(exc))
            self.panel.status.config(text=tr('recipes.unsaved') + ('' if field else ': ' + str(exc)))
            return False

    def create(self, category=''):
        if self.error:
            messagebox.showerror(tr('recipes.title'), self.error, parent=self.app)
            return
        if not self.app._save_editors():
            return
        recipe = dict(schema_version=1, id=self.store.free_id(), category=category, name=tr('recipes.new'), result='',
                      result_count=1, ingredients=[], availability={'type': 'always'})
        self.select(recipe, persisted=False)

    def add(self, category):
        if self.error or not self.app._save_editors():return
        from gothic_editor.ui.windows.recipe_add import AddRecipeDialog, GameRecipeDialog
        dialog = AddRecipeDialog(self.app)
        dialog.show_centered(modal=True)
        self.app.wait_window(dialog)
        if dialog.result == 'new':self.create(category)
        elif dialog.result == 'game':
            try:
                from gothic_editor.core.game_recipes import game_recipes
                recipes, skipped = game_recipes(self.app.repo.game)
                # The destination category is determined by the '+' the user chose.
                picker = GameRecipeDialog(self.app, recipes, skipped)
                picker.show_centered(modal=True)
                self.app.wait_window(picker)
                if picker.result is None:return
                data = deepcopy(picker.result)
                data['id'] = self.store.free_id(data['id'])
                data['category'] = category
                saved=self.app.history.capture((self.store.path(data['id']),))
                self.store.save(data)
                self.app.history.record(saved)
                self.load()
                self.select(data)
            except (OSError, ValueError) as exc:
                messagebox.showerror(tr('recipes.title'), str(exc), parent=self.app)

    def categories(self):
        if not self.app._save_editors():return
        from gothic_editor.ui.windows.recipe_categories import RecipeCategoriesWindow
        def saved():
            if self.current is not None:self.select(self.current)
            self.app.recipe_list.populate()
        try:
            window = RecipeCategoriesWindow(self.app, self.app.repo.root, saved)
            window.show_centered(modal=True)
        except (OSError, ValueError) as exc:
            messagebox.showerror(tr('recipes.categories'), str(exc), parent=self.app)

    def category_action(self, action, code=None):
        if not self.app._save_editors():return
        from gothic_editor.core.recipe_categories import RecipeCategories
        from gothic_editor.ui.windows.recipe_categories import RecipeCategoryDialog
        store = RecipeCategories(self.app.repo.root)
        selected = self.current['id'] if self.current else None
        def refresh():
            self.deselect()
            self.panel.show(None)
            self.load()
            recipe = next((r for r in self.items if r['id']==selected), None)
            if recipe is not None:self.select(recipe)
        try:
            category = next((row for row in store.load() if row['id']==code), None)
            if action in ('create', 'edit'):
                window = RecipeCategoryDialog(self.app, store, refresh,
                                              category if action == 'edit' else None,
                                              parent=code if action == 'create' else None)
                window.show_centered(modal=True)
            elif action == 'duplicate':
                store.duplicate(code)
                refresh()
            elif action == 'delete' and messagebox.askyesno(tr('recipes.category'), tr('recipes.confirm_delete_category'), parent=self.app):
                store.change(code, None)
                refresh()
        except (OSError, ValueError) as exc:
            messagebox.showerror(tr('recipes.category'), str(exc), parent=self.app)

    def duplicate(self):
        if self.current is None or not self.app._save_editors():
            return
        try:
            data = self.store.duplicate(self.current)
            self.app.history.record({},(self.store.path(data['id']),))
            self.load()
            self.select(data)
        except (OSError, ValueError) as exc:
            messagebox.showerror(tr('recipes.title'), str(exc), parent=self.app)

    def delete(self):
        if self.current is None or not messagebox.askyesno(tr('recipes.title'), tr('recipes.confirm_delete'), parent=self.app):
            return
        try:
            if self.persisted:
                saved=self.app.history.capture((self.store.path(self.current['id']),))
                self.store.delete(self.current['id'])
                self.app.history.record(saved)
            self.deselect()
            self.panel.show(None)
            self.load()
        except (OSError, ValueError) as exc:
            messagebox.showerror(tr('recipes.title'), str(exc), parent=self.app)

    def choose(self, variable):
        if self.choice is not None:
            self.choice.lift()
            return
        def close():
            self.choice.destroy()
            self.choice = None
        def accept(value):
            variable.set(value)
            close()
        groups = []
        # Repository items already apply project precedence over Gothic instances.
        for origin, title in (('project', tr('recipes.project')), ('game', 'Gothic')):
            options = [(item.instance + ' — ' + item.title, item.instance)
                       for item in self.app.repo.items if (item.origin == 'project') == (origin == 'project')]
            groups.append((title, options))
        self.choice = GroupedChoiceWindow(self.app, groups, variable.get(), tr('recipes.choose'), accept, close)
        self.choice.show()
