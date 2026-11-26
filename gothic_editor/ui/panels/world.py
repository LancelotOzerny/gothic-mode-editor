"""Static world resource browser and forms using the common dark UI widgets."""
from pathlib import Path

from gothic_editor.core.world_resources import WORLD_CATEGORIES
from gothic_editor.ui.actions import ActionRegistry
from gothic_editor.ui.widgets import MUTED, label
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from .hierarchy import CategoryRow, HierarchyBrowser, HierarchyCategory, HierarchyRow


class WorldPanel(HierarchyBrowser):
    def __init__(self, parent, on_select, on_select_npc=lambda npc: None):
        super().__init__(parent)
        self.on_select = on_select
        self.on_select_npc = on_select_npc
        self.owner, self.origin = self, 'project'
        self.npcs = []
        self.resources = []
        self.entries, self.npc_entries = {}, {}
        self.grouped, self.category_rows, self.rows = {}, {}, {}
        self.selected = None
        self.on_add = lambda: None
        self.on_remove = lambda: None
        self.import_button = self.add_header_action(lambda: self.on_add(), 'Добавить из Gothic')
        self.area = ScrollableArea(self)
        self.area.pack(fill='both', expand=True)
        label(self.area.content, 'Выберите проект', fg=MUTED).pack(fill='x', padx=10, pady=8)
        self.search.trace_add('write', lambda *_: self.rebuild())

    def set_resources(self, resources, npcs=()):
        resources=list(resources)
        npcs=list(npcs)
        if resources==self.resources and npcs==self.npcs:return
        self.resources = resources
        self.npcs = npcs
        self.rebuild()
        if not self.search.get().strip() and self.selected not in self.entries and self.selected not in self.npc_entries:
            self.selected = None

    def rebuild(self):
        position = self.area.canvas.yview()
        for child in self.area.content.winfo_children():
            child.destroy()
        self.entries, self.npc_entries = {}, {}
        self.grouped, self.category_rows, self.rows = {}, {}, {}
        query = self.search.get().strip().casefold()
        for category, title in WORLD_CATEGORIES.items():
            matches = {
                'model:' + resource.name.casefold(): resource for resource in self.resources
                if resource.category == category and (query in resource.title.casefold() or query in title.casefold())
            }
            if matches:
                self.entries.update(matches)
                self.grouped[category] = list(matches)
                CategoryRow(self, self.area.content, HierarchyCategory(category, title), 0)
        self.npc_entries = {
            'npc:' + npc.instance.casefold(): npc for npc in self.npcs
            if query in npc.title.casefold() or query in npc.instance.casefold() or query in 'npc'
        }
        if self.npc_entries:
            self.grouped['npcs'] = list(self.npc_entries)
            CategoryRow(self, self.area.content, HierarchyCategory('npcs', 'NPC'), 0)
        if not (self.entries or self.npc_entries):
            label(self.area.content, 'Ничего не найдено', fg=MUTED).pack(padx=12, pady=15)
        self.area.canvas.yview_moveto(position[0] if position else 0)

    def bind_category(self, row, category):
        super().bind_category(row, category)
        row.header.bind_row('<Button-3>', lambda event: self.context(event))

    def navigate_horizontal(self, area, row, opened):
        branch = row.master
        if isinstance(branch, CategoryRow) and branch.opened != opened:
            super().navigate_horizontal(area, row, opened)
        elif opened and isinstance(branch, CategoryRow):
            child = next(self.visible_rows(branch.content), None)
            if child is not None:
                self.activate_row(area, child)
        elif not opened:
            container = branch.master if isinstance(branch, CategoryRow) else branch
            if isinstance(container.master, CategoryRow):
                self.activate_row(area, container.master.header)

    def count(self, category):
        return len(self.grouped.get(category.key, ())) + sum(self.count(child) for child in category.children)

    @staticmethod
    def caption(value):
        return value.title + ('  • Проект' if value.overridden else '')

    def row_item(self, parent, key, level):
        value = self.npc_entries[key] if key in self.npc_entries else self.entries[key]
        row = HierarchyRow(parent, self.caption(value), level)
        self.rows[key] = row
        row.set_selected(key == self.selected and self.active_category is None)
        self.bind_activate(row, lambda: self.select(key))
        row.bind_row('<Button-3>', lambda event: self.context(event, key))

    def select_category(self, key):
        super().select_category(key)
        row = self.rows.get(self.selected)
        if row is not None:
            row.set_selected(key is None)

    def select(self, key):
        if key in self.npc_entries:
            result = self.on_select_npc(self.npc_entries[key])
        else:
            result = self.on_select(self.entries[key])
        if result is False:
            return False
        self.select_category(None)
        previous = self.rows.get(self.selected)
        if previous is not None:
            previous.set_selected(False)
        self.selected = key
        row = self.rows.get(key)
        if row is not None:
            row.set_selected(True)
        return True

    def _actions(self, key=None):
        actions=ActionRegistry()
        actions.register('add','Добавить из Gothic',self.on_add)
        actions.register('remove','Удалить из проекта',self.on_remove,
                         enabled=lambda:key is not None)
        return actions

    def context(self, event, key=None):
        if key is not None and not self.select(key):return
        actions=self._actions(key)
        keys=('add','remove') if key is not None else ('add',)
        self.popup(event,[(actions.get(action).label,actions.get(action).execute)
                          for action in keys])

    def update_resource(self, resource):
        """Update a model caption without recreating unaffected rows."""
        self.resources=[resource if value.name.casefold()==resource.name.casefold() else value
                        for value in self.resources]
        key='model:'+resource.name.casefold()
        query=self.search.get().strip().casefold()
        if query and (key not in self.entries or query not in resource.title.casefold()):
            self.rebuild()
        elif key in self.entries:
            self.entries[key]=resource
            row=self.rows.get(key)
            if row is not None and row.winfo_exists():
                row.title_label.configure(text=self.caption(resource))

    def update_npc(self, npc):
        self.npcs = [npc if value.instance == npc.instance else value for value in self.npcs]
        key = 'npc:' + npc.instance.casefold()
        if self.search.get().strip():
            self.rebuild()
        elif key in self.npc_entries:
            self.npc_entries[key] = npc
            row = self.rows.get(key)
            if row is not None:
                row.title_label.configure(text=self.caption(npc))


class WorldPropertiesPanel(Panel):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        label(self, 'Свойства', font=('Arial', 10, 'bold')).pack(fill='x', padx=14, pady=(14, 0))
        self.caption = label(self, 'Выберите объект мира', fg=MUTED, wraplength=280)
        self.caption.pack(fill='x', padx=14, pady=(4, 20))
        self.area = ScrollableArea(self)
        self.area.pack(fill='both', expand=True)
        self.resource = None

    def show(self, resource, preview=None):
        self.resource = resource
        self.caption.config(text=resource.name if resource else 'Выберите объект мира')
        for child in self.area.content.winfo_children():child.destroy()
        if resource is None:return
        group = self.add_group('Модель', parent=self.area.content)
        group.add_field('Ресурс', value=resource.name, readonly=True)
        group.add_field('Категория', value=WORLD_CATEGORIES[resource.category], readonly=True)
        label(group.body, 'Замена в проекте' if resource.overridden else 'Исходный ресурс',
              fg=MUTED).pack(fill='x', padx=8, pady=6)
        group.add_button('Экспорт модели', self.controller.export_model)
        replace=group.add_button('Заменить модель', self.controller.replace_model)
        if Path(resource.source.name).suffix.lower() in ('.mdm','.mdl'):
            replace.config(state='disabled')
            label(group.body,'Анимированный объект: замена статической моделью недоступна.',
                  fg=MUTED,wraplength=260).pack(fill='x',padx=8,pady=6)
        if resource.overridden:group.add_button('Отменить замену модели', self.controller.reset_model)
        textures = self.add_group('Материалы и текстуры', parent=self.area.content)
        if preview is None:
            label(textures.body, 'Загрузка…', fg=MUTED).pack(padx=8, pady=8)
            return
        materials = list(dict.fromkeys((preview.mesh.material_names[index] if index < len(preview.mesh.material_names)
                                      else '', name) for index,name in enumerate(preview.mesh.texture_names)))
        if not materials:
            label(textures.body, 'У модели нет назначенных материалов', fg=MUTED).pack(padx=8, pady=8)
        for material,name in materials:
            label(textures.body, material or 'Материал без имени', anchor='w', wraplength=260,
                  font=('Arial',10,'bold')).pack(fill='x',padx=8,pady=(12,4))
            label(textures.body, name or 'Текстура не назначена', anchor='w', wraplength=260).pack(fill='x', padx=8, pady=(0, 4))
            if not name:continue
            textures.add_button('Просмотреть текстуру', lambda value=name:self.controller.texture(value, 'preview'))
            textures.add_button('Экспорт текстуры', lambda value=name:self.controller.texture(value, 'export'))
            textures.add_button('Заменить текстуру', lambda value=name:self.controller.replace_texture(value))
            if self.controller.texture_overridden(name):
                textures.add_button('Отменить замену текстуры', lambda value=name:self.controller.reset_texture(value))
