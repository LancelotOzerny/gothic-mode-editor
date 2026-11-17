"""Static world resource browser and forms using the common dark UI widgets."""
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from gothic_editor.core.world_resources import WORLD_CATEGORIES
from gothic_editor.ui.widgets import PANEL, INPUT, TXT, MUTED, label
from gothic_editor.ui.widgets.inputs import make_entry
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea, attach_scrollbar


class WorldPanel(Panel):
    def __init__(self, parent, on_select, on_select_npc=lambda npc:None):
        super().__init__(parent)
        self.on_select = on_select
        self.on_select_npc = on_select_npc
        self.npcs = []
        self.npc_entries = {}
        self.resources = []
        self.entries = {}
        self.on_add=lambda:None
        self.on_remove=lambda:None
        self.add_button('Добавить из Gothic',lambda:self.on_add()).pack(fill='x',padx=10,pady=(10,0))
        self.add_button('Удалить из проекта',lambda:self.on_remove()).pack(fill='x',padx=10,pady=(6,0))
        self.search = tk.StringVar(self)
        make_entry(self, textvariable=self.search).pack(fill='x', padx=10, pady=10)
        style = ttk.Style(self)
        style.configure('World.Treeview', background=PANEL, fieldbackground=PANEL,
                        foreground=TXT, borderwidth=0, rowheight=30)
        style.layout('World.Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        style.map('World.Treeview', background=[('selected', INPUT)], foreground=[('selected', TXT)])
        body = tk.Frame(self, bg=PANEL)
        body.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(body, show='tree', style='World.Treeview', selectmode='browse')
        self.tree.column('#0', width=240, minwidth=80)
        attach_scrollbar(body, self.tree)
        self.tree.pack(fill='both', expand=True)
        self.empty = label(self, 'Выберите проект', fg=MUTED)
        self.empty.pack(fill='x', padx=10, pady=8)
        self.search.trace_add('write', lambda *_: self.rebuild())
        self.tree.bind('<<TreeviewSelect>>', self._select)

    def set_resources(self, resources, npcs=()):
        self.resources = resources
        self.npcs = list(npcs)
        self.rebuild()

    def rebuild(self):
        selected = self.tree.selection()
        opened = {node: self.tree.item(node, 'open') for node in self.tree.get_children('')}
        self.tree.delete(*self.tree.get_children(''))
        self.entries = {}
        self.npc_entries = {}
        query = self.search.get().strip().casefold()
        objects=None
        for category, title in WORLD_CATEGORIES.items():
            matches = [resource for resource in self.resources if resource.category == category
                       and (not query or query in resource.title.casefold() or query in title.casefold())]
            if not matches:continue
            if objects is None:
                objects=self.tree.insert('', 'end', iid='objects', text='Объекты',open=opened.get('objects',True))
            self.tree.insert(objects, 'end', iid=category, text=f'{title} [{len(matches)}]',
                             open=bool(query) or opened.get(category, False))
            for resource in matches:
                key = 'model:' + resource.name.casefold()
                self.entries[key] = resource
                self.tree.insert(category, 'end', iid=key,
                                 text=resource.title + ('  • Проект' if resource.overridden else ''))
        matches=[npc for npc in self.npcs if not query or query in npc.title.casefold() or query in npc.instance.casefold() or query in 'npc']
        if matches:
            self.tree.insert('','end',iid='npcs',text=f'NPC [{len(matches)}]',open=bool(query) or opened.get('npcs',False))
            for npc in matches:
                key='npc:'+npc.instance.casefold()
                self.npc_entries[key]=npc
                self.tree.insert('npcs','end',iid=key,text=npc.title+('  • Проект' if npc.overridden else ''))
        self.empty.config(text='' if self.entries or self.npc_entries else 'Ничего не найдено')
        if selected and self.tree.exists(selected[0]):self.tree.selection_set(selected[0])

    def _select(self, _event=None):
        selected = self.tree.selection()
        if selected and selected[0] in self.entries:self.on_select(self.entries[selected[0]])
        elif selected and selected[0] in self.npc_entries:self.on_select_npc(self.npc_entries[selected[0]])

    def update_npc(self,npc):
        self.npcs=[npc if value.instance==npc.instance else value for value in self.npcs]
        key='npc:'+npc.instance.casefold()
        if key in self.npc_entries:
            self.npc_entries[key]=npc
            self.tree.item(key,text=npc.title+('  • Проект' if npc.overridden else ''))


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
