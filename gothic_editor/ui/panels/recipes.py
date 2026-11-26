"""Recipe list and property form built from the editor's shared widgets."""
import tkinter as tk
from gothic_editor.core.localization import tr
from gothic_editor.ui.actions import ActionRegistry
from gothic_editor.ui.widgets import label, MUTED
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets.item_binding import ItemBindingTile
from .hierarchy import CategoryRow, HierarchyBrowser, HierarchyCategory, HierarchyRow


class RecipeListPanel(HierarchyBrowser):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.owner, self.origin = self, 'project'
        self.category_rows, self.grouped = {}, {}
        self.selected_recipe_row = None
        self.recipe_rows = {}
        self.add_header_action(lambda: controller.category_action('create'), tr('recipes.add_category'))
        self.area = ScrollableArea(self)
        self.area.pack(fill='both', expand=True)
        self.search.trace_add('write', lambda *_: self.populate())

    def populate(self):
        from gothic_editor.core.recipe_categories import RecipeCategories
        position = self.area.canvas.yview()
        for child in self.area.content.winfo_children():
            child.destroy()
        self.category_rows, self.grouped = {}, {}
        self.selected_recipe_row = None
        self.recipe_rows = {}
        query = self.search.get().strip().casefold()
        if self.controller.error:
            label(self.area.content, self.controller.error, wraplength=270).pack(fill='x', padx=12)
            return
        if not self.controller.app.repo.root:return
        categories = RecipeCategories(self.controller.app.repo.root).load()
        if any(not row.get('category') for row in self.controller.items) or (self.controller.current is not None and not self.controller.current.get('category')):
            categories += [{'id': '', 'name': tr('recipes.root_category')}]
        current = self.controller.current
        if current is not None and not self.controller.persisted and not any(r['id']==current['id'] for r in self.controller.items):
            items = self.controller.items + [current]
        else:items = self.controller.items
        indexed = {row['id']: row for row in categories}
        nested = {row['id']: [] for row in categories}
        roots = []
        for category in categories:
            parent = category.get('parent') or ''
            if parent and parent in nested:
                nested[parent].append(category['id'])
            else:
                roots.append(category['id'])

        def ancestors(code):
            while code and code in indexed:
                yield indexed[code]['name']
                code = indexed[code].get('parent') or ''

        for category in categories:
            code = category['id']
            title_match = any(query in title.casefold() for title in ancestors(code))
            self.grouped[code] = [recipe for recipe in items
                if recipe.get('category', '') == code and
                (not query or title_match or query in (recipe['id'] + ' ' + recipe['name']).casefold())]

        def node(code):
            category = indexed[code]
            return HierarchyCategory(code, category['name'],
                                     tuple(node(child) for child in nested[code]))

        for code in roots:
            category = node(code)
            if not query or self.count(category) or query in category.title.casefold():
                CategoryRow(self, self.area.content, category, 0)
        self.area.canvas.yview_moveto(position[0] if position else 0)

    def bind_category(self, row, category):
        super().bind_category(row, category)
        row.header.bind_row('<Button-3>', lambda event: self.category_context(event, category.key))

    def count(self, category):
        return len(self.grouped.get(category.key, [])) + sum(
            self.count(child) for child in category.children)

    def select_category(self, key):
        super().select_category(key)
        if self.selected_recipe_row is not None:
            self.selected_recipe_row.set_selected(key is None)

    def row_item(self, parent, recipe, level):
        row = HierarchyRow(parent, recipe['name'], level)
        self.recipe_rows[recipe['id']] = row
        current = self.controller.current
        if current is not None and recipe['id'] == current['id']:
            self.selected_recipe_row = row
            row.set_selected(self.active_category is None)
        self.bind_activate(row, lambda: self.controller.select(recipe))
        row.bind_row('<Button-3>', lambda event: self.recipe_context(event, recipe))

    def update_recipe(self,previous,updated):
        """Update a visible recipe without reconstructing the category tree."""
        if previous is None or previous['id'] != updated['id'] or previous.get('category') != updated.get('category'):
            self.populate()
            return
        query=self.search.get().strip().casefold()
        matches=lambda value:not query or query in (value['id']+' '+value['name']).casefold()
        if matches(previous)!=matches(updated):
            self.populate()
            return
        group=self.grouped.get(updated.get('category',''))
        if group is not None:
            for index,value in enumerate(group):
                if value['id']==updated['id']:
                    group[index]=updated
                    break
        row=self.recipe_rows.get(updated['id'])
        if row is not None and row.winfo_exists():
            row.title_label.configure(text=updated['name'])

    def _category_actions(self,code):
        actions=ActionRegistry()
        for key in ('edit','duplicate','delete'):
            actions.register(key,tr('recipes.'+key),
                lambda current=key:self.controller.category_action(current,code),
                enabled=lambda:bool(code))
        actions.register('subcategory','Создать подкатегорию',
                         lambda:self.controller.category_action('create',code),
                         enabled=lambda:bool(code))
        actions.register('import','Импорт всех рецептов',
                         lambda:self.controller.import_category(code),
                         enabled=lambda:bool(code))
        actions.register('add',tr('recipes.add_recipe'),lambda:self.controller.add(code))
        return actions

    def _recipe_actions(self):
        actions=ActionRegistry()
        actions.register('duplicate',tr('recipes.duplicate'),self.controller.duplicate)
        actions.register('delete',tr('recipes.delete'),self.controller.delete)
        return actions

    def category_context(self, event, code):
        actions=self._category_actions(code)
        keys=('edit','duplicate','delete','subcategory','import') if code else ()
        self.popup(event,[(actions.get(key).label,lambda action=key:actions.invoke(action))
                          for key in (*keys,'add')])

    def recipe_context(self, event, recipe):
        self.controller.select(recipe)
        if self.controller.current is None or self.controller.current['id']!=recipe['id']:return
        actions=self._recipe_actions()
        self.popup(event,[(actions.get(key).label,lambda action=key:actions.invoke(action))
                          for key in ('duplicate','delete')])


class RecipePropertiesPanel(Panel):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        label(self, tr('recipes.title')).pack(fill='x', padx=12, pady=12)
        self.status = label(self, '', fg=MUTED, wraplength=300)
        self.status.pack(fill='x', padx=12)
        self.area = ScrollableArea(self)
        self.area.pack(fill='both', expand=True)
        self.fields, self.errors, self.rows = {}, {}, []

    def field(self, group, key, value, **options):
        variable = tk.StringVar(self, value=str(value))
        field = group.add_field(tr('recipes.' + key), variable=variable, **options)
        self.controller.watch(variable)
        self.fields[key] = field
        error = label(group.body, '', wraplength=300)
        error.pack(fill='x', padx=8)
        self.errors[key] = error
        return variable

    def show(self, data):
        for child in self.area.content.winfo_children():
            child.destroy()
        self.fields, self.errors, self.rows = {}, {}, []
        if data is None:
            self.status.config(text=tr('recipes.select'))
            return
        group = self.add_group(tr('recipes.general'), parent=self.area.content)
        from gothic_editor.core.recipe_categories import RecipeCategories
        category_rows = RecipeCategories(self.controller.app.repo.root).load()
        by_id = {row['id']: row for row in category_rows}
        def category_title(row):
            titles = [row['name']]
            parent = row.get('parent') or ''
            while parent:
                ancestor = by_id[parent]
                titles.insert(0, ancestor['name'])
                parent = ancestor.get('parent') or ''
            return ' / '.join(titles)
        options = [(tr('recipes.root_category'), '')] + [
            (category_title(row), row['id']) for row in category_rows]
        self.field(group, 'category', data.get('category', ''), kind='choice', options=options)
        for key in ('id', 'name', 'result', 'result_count'):
            variable = self.field(group, key, data[key])
            if key == 'result':
                group.add_button(tr('recipes.choose'), lambda v=variable: self.controller.choose(v))
        ingredients = self.add_group(tr('recipes.ingredients'), parent=self.area.content)
        self.ingredient_group = ingredients
        self.rows_frame = tk.Frame(ingredients.body, bg=ingredients.body.cget('bg'))
        self.rows_frame.pack(fill='x')
        self.rows_frame.bind('<Configure>', lambda _: self.reflow_ingredients(), add='+')
        self.errors['ingredients'] = label(ingredients.body, '', wraplength=300)
        self.errors['ingredients'].pack(fill='x')
        for row in data['ingredients']:
            self.add_row(row, notify=False)
        self.add_row({'instance': '', 'count': 1}, notify=False)
        availability = self.add_group(tr('recipes.availability'), parent=self.area.content)
        self.field(availability, 'availability', data['availability']['type'], kind='choice',
                   options=[(tr('recipes.always'), 'always'),
                            (tr('recipes.global_variable'), 'global_variable'),
                            ('Навык алхимии Gothic', 'stock_talent')])
        self.field(availability, 'variable', data['availability'].get('variable', ''))
        group_talent = tk.StringVar(self, value=data['availability'].get('talent', ''))
        self.talent_field = availability.add_field('Навык Gothic', variable=group_talent)
        self.controller.watch(group_talent)
        self.fields['talent'] = self.talent_field
        self.variable_field = self.fields['variable']
        self.talent_field = self.fields['talent']
        def update_availability_fields(_event=None):
            value = self.fields['availability'].get()
            self.variable_field.configure(state='normal' if value == 'global_variable' else 'disabled')
            self.talent_field.configure(state='normal' if value == 'stock_talent' else 'disabled')
        self.fields['availability'].bind('<<ComboboxSelected>>', update_availability_fields)
        update_availability_fields()
        self.status.config(text=tr('recipes.saved') if self.controller.persisted else tr('recipes.dirty'))

    def add_row(self, row=None, notify=True):
        row = row or {'instance': '', 'count': 1}
        instance = tk.StringVar(self, value=row['instance'])
        count = tk.StringVar(self, value=str(row['count']))
        record = (None, instance, count)
        if instance.get().strip() and self.rows and not self.rows[-1][1].get().strip():
            self.rows.insert(len(self.rows) - 1, record)
        else:
            self.rows.append(record)
        self.controller.watch(instance)
        self.controller.watch(count)
        instance.trace_add('write', lambda *_: self._instance_changed(instance))
        self._render_tile(record)
        if notify:
            self.controller.changed()

    def _render_tile(self, record):
        def title_for(instance):
            item = next((item for item in self.controller.app.repo.items
                         if item.instance.casefold() == instance.casefold()), None)
            return item.title if item else instance
        def current_record():
            return next((row for row in self.rows if row[1] is record[1]), None)
        tile = ItemBindingTile(
            self.rows_frame, record[1], record[2],
            self.controller.choose,
            lambda: self.remove_row(current_record()),
            self.controller.changed,
            title_for,
        )
        current = (tile, record[1], record[2])
        self.rows[self.rows.index(record)] = current
        tile.grid()
        self.reflow_ingredients()

    def reflow_ingredients(self):
        width = max(self.rows_frame.winfo_width(), ItemBindingTile.SIZE)
        columns = max(1, (width + 20) // (ItemBindingTile.SIZE + 20))
        gap = (width - columns * ItemBindingTile.SIZE) // (columns - 1) if columns > 1 else 20
        children = [row[0] for row in self.rows]
        for index, child in enumerate(children):
            child.grid_configure(row=index // columns, column=index % columns,
                                 padx=(0 if index % columns == 0 else gap, 0),
                                 pady=(0, 20))

    def remove_row(self, record):
        record[0].destroy()
        self.rows.remove(record)
        if not any(not row[1].get().strip() for row in self.rows):
            self.add_row({'instance': '', 'count': 1}, notify=False)
        self.controller.changed()
        self.reflow_ingredients()

    def remove_ingredient(self, record):
        self.remove_row(record)

    def _instance_changed(self, variable):
        record = next((row for row in self.rows if row[1] is variable), None)
        if record is None or not variable.get().strip():
            return
        if record is self.rows[-1]:
            self.add_row({'instance': '', 'count': 1}, notify=False)

    def clear_errors(self):
        for error in self.errors.values():
            error.config(text='')
