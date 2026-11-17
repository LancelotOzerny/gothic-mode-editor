"""Recipe list and property form built from the editor's shared widgets."""
import tkinter as tk
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import label, make_entry, MUTED
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets.buttons import PropertyButton


class RecipeListPanel(Panel):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        label(self, tr('recipes.alchemy')).pack(fill='x', padx=12, pady=12)
        self.search = tk.StringVar(self)
        make_entry(self, textvariable=self.search).pack(fill='x', padx=12)
        for key in ('create', 'duplicate', 'delete'):
            PropertyButton(self, getattr(controller, key), text=tr('recipes.' + key)).pack(fill='x', padx=12, pady=3)
        self.area = ScrollableArea(self)
        self.area.pack(fill='both', expand=True)
        self.search.trace_add('write', lambda *_: self.populate())

    def populate(self):
        for child in self.area.content.winfo_children():
            child.destroy()
        query = self.search.get().casefold()
        if self.controller.error:
            label(self.area.content, self.controller.error, wraplength=270).pack(fill='x', padx=12)
        for recipe in self.controller.items:
            title = recipe['id'] + ' — ' + recipe['name']
            if query in title.casefold():
                button = PropertyButton(self.area.content, lambda r=recipe: self.controller.select(r), text=title, align='left')
                button.pack(fill='x')
                button.set_selected(self.controller.current is not None and recipe['id'] == self.controller.current['id'])


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
        for key in ('id', 'name', 'result', 'result_count'):
            variable = self.field(group, key, data[key])
            if key == 'result':
                group.add_button(tr('recipes.choose'), lambda v=variable: self.controller.choose(v))
        ingredients = self.add_group(tr('recipes.ingredients'), parent=self.area.content)
        self.ingredient_group = ingredients
        self.rows_frame = tk.Frame(ingredients.body, bg=ingredients.body.cget('bg'))
        self.rows_frame.pack(fill='x')
        self.errors['ingredients'] = label(ingredients.body, '', wraplength=300)
        self.errors['ingredients'].pack(fill='x')
        ingredients.add_button(tr('recipes.add'), self.add_row)
        for row in data['ingredients']:
            self.add_row(row, notify=False)
        availability = self.add_group(tr('recipes.availability'), parent=self.area.content)
        self.field(availability, 'availability', data['availability']['type'], kind='choice',
                   options=[(tr('recipes.always'), 'always'), (tr('recipes.global_variable'), 'global_variable')])
        variable = self.field(availability, 'variable', data['availability'].get('variable', ''))
        self.variable_field = self.fields['variable']
        self.variable_field.configure(state='normal' if data['availability']['type'] == 'global_variable' else 'disabled')
        self.fields['availability'].bind('<<ComboboxSelected>>', lambda _: self.variable_field.configure(
            state='normal' if self.fields['availability'].get() == 'global_variable' else 'disabled'))
        self.status.config(text=tr('recipes.saved') if self.controller.persisted else tr('recipes.dirty'))

    def add_row(self, row=None, notify=True):
        from gothic_editor.ui.widgets.form import FormGroup
        row = row or {'instance': '', 'count': 1}
        group = FormGroup(self.rows_frame, tr('recipes.ingredient'))
        group.pack(fill='x')
        instance = tk.StringVar(self, value=row['instance'])
        count = tk.StringVar(self, value=str(row['count']))
        group.add_field(tr('recipes.item'), variable=instance)
        group.add_button(tr('recipes.choose'), lambda: self.controller.choose(instance))
        group.add_field(tr('recipes.count'), variable=count)
        record = (group, instance, count)
        self.rows.append(record)
        group.add_button(tr('recipes.remove'), lambda: self.remove_row(record))
        self.controller.watch(instance)
        self.controller.watch(count)
        if notify:
            self.controller.changed()

    def remove_row(self, record):
        self.rows.remove(record)
        record[0].destroy()
        self.controller.changed()

    def clear_errors(self):
        for error in self.errors.values():
            error.config(text='')
