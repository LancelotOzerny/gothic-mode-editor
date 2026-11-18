"""Project hierarchy with lazy category rows and animated disclosure icons."""
from __future__ import annotations

import tkinter as tk
from time import monotonic

from gothic_editor.core.categories import CATEGORIES, Category, classify, EDITABLE_CATEGORIES
from gothic_editor.core.item_hierarchy import HierarchyNode
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets.icons import IconImages
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets import BG, PANEL, INPUT, TXT, MUTED, ACCENT, label, make_entry


class CategoryRow(tk.Frame):
    def __init__(self, section, parent, category, level):
        super().__init__(parent, bg=PANEL)
        self.section = section
        self.category = category
        section.category_rows[category.key] = self
        self.level = level
        self.key = (section.origin, category.key)
        self.frames = section.owner.arrow_frames
        self.opened = bool(section.owner.expanded.get(self.key)) or bool(section.owner.search.get().strip())
        self.angle = len(self.frames) - 1 if self.opened else 0
        self.animation = None
        self.built = False
        self.pack(fill='x')
        row = tk.Frame(self, bg=PANEL, height=32)
        row.pack(fill='x', padx=5, pady=1)
        row.pack_propagate(False)
        tk.Frame(row, bg=PANEL, width=level * 13).pack(side='left')
        self.arrow = tk.Label(row, image=self.frames[self.angle], bg=PANEL, cursor='hand2')
        self.arrow.pack(side='left', padx=(3, 5))
        self.arrow.bind('<Button-1>', lambda _: self.toggle())
        self.group_icons = {}
        if getattr(category, 'kind', None) == 'group':
            icons = IconImages.shared(self)
            self.group_icons = {color: icons.frames('editor/union.png', 18, ACCENT, color)[0]
                                for color in (PANEL, '#26364a', '#3a4d66')}
            self.icon_label = tk.Label(row, image=self.group_icons[PANEL], bg=PANEL)
        else:
            self.icon_label = label(row, getattr(category, 'icon', '▦'), fg=ACCENT,
                                    font=('Segoe UI Symbol', 13))
        self.icon_label.pack(side='left', padx=(0, 5))
        caption = (category.name if isinstance(category, HierarchyNode) else
                   getattr(section.owner, 'category_title',
                           lambda value: tr('categories.' + value.key))(category))
        title = label(row, caption + f' [{section.count(category)}]',
                      font=('Arial', 10, 'bold'), anchor='w')
        title.pack(side='left', fill='x', expand=True)
        self.title_label=title
        title.bind('<Button-1>', lambda _: self.toggle())
        self.content = tk.Frame(self, bg=PANEL)
        if self.opened:
            self.show_content()
        self.bind('<Destroy>', self.cancel_animation, add='+')
        self.header = row
        self._hover_widgets = (row, *row.winfo_children())
        for widget in self._hover_widgets:
            widget.bind('<Enter>', lambda _: self.set_hover(True), add='+')
            widget.bind('<Leave>', lambda _: self.set_hover(False), add='+')
            if hasattr(section.owner, 'context_node'):
                widget.bind('<Button-3>', lambda event: section.owner.context_node(event, category))
                if widget is not self.arrow:
                    widget.bind('<Button-1>', lambda event: section.owner.press_node(event,category))
                    widget.bind('<B1-Motion>',section.owner.drag_motion)
                    widget.bind('<ButtonRelease-1>',section.owner.release_item)
        self.set_hover(False)
        # Recipe rows share this widget but retain their existing add action.
        if not hasattr(section.owner, 'context_node') and getattr(section.owner, 'can_create', lambda _:False)(category):
            plus = tk.Label(row, text='+', bg=INPUT, fg=ACCENT, font=('Arial',14,'bold'), width=2, cursor='hand2')
            plus.pack(side='right', padx=5)
            plus.bind('<Button-1>', lambda _: section.owner.on_create(category.key))

    def select_node(self, event=None):
        if event is not None and event.state & 1:
            self.section.owner.toggle_selection(self.category)
        elif self.section.owner.select_node(self.category) and self.winfo_exists():self.toggle()

    def set_hover(self, active):
        selected = (self.section.owner.is_selected(self.category) if hasattr(self.section.owner,'is_selected')
                    else getattr(self.section.owner,'selected_node',None)==self.category.key)
        color = '#3a4d66' if selected else '#26364a' if active else PANEL
        target = getattr(self.section.owner,'drop_target',None)
        if target is not None and target[0]==self.category.key:
            color = '#315b50' if target[1] else '#683f48'
        for widget in self._hover_widgets:widget.configure(bg=color)
        if self.group_icons:
            if color not in self.group_icons:
                self.group_icons[color] = IconImages.shared(self).frames('editor/union.png',18,ACCENT,color)[0]
            self.icon_label.configure(image=self.group_icons[color])

    def show_content(self):
        if not self.built:
            for child in self.category.children:
                if not self.section.owner.search.get().strip() or self.section.count(child):
                    CategoryRow(self.section, self.content, child, self.level + 1)
            for item in self.section.grouped.get(self.category.key, []):
                self.section.row_item(self.content, item, self.level + 1)
            self.built = True
        self.content.pack(fill='x')

    def toggle(self):
        self.opened = not self.opened
        self.section.owner.expanded[self.key] = self.opened
        if self.opened:
            self.show_content()
        else:
            self.content.pack_forget()
        self.cancel_animation()
        self.start_angle = self.angle
        self.target_angle = len(self.frames) - 1 if self.opened else 0
        self.started = monotonic()
        self.tick()

    def tick(self):
        progress = min(1., (monotonic() - self.started) / .16)
        eased = progress * progress * (3 - 2 * progress)
        self.angle = self.start_angle + (self.target_angle - self.start_angle) * eased
        self.arrow.config(image=self.frames[round(self.angle)])
        if progress < 1:
            self.animation = self.after(16, self.tick)
        else:
            self.animation = None

    def cancel_animation(self, event=None):
        if event is not None and event.widget is not self:
            return
        if self.animation is not None:
            self.after_cancel(self.animation)
            self.animation = None


class HierarchySection(Panel):
    def __init__(self, owner, parent, origin):
        super().__init__(parent, bg=PANEL)
        self.owner = owner
        self.origin = origin
        self.items = []
        self.grouped = {}
        self.item_rows = {}
        self.category_rows = {}
        self.highlighted = None
        self.heading = label(self, '', fg=ACCENT, anchor='w', font=('Arial', 10, 'bold'))
        self.heading.pack(fill='x', padx=10, pady=8)
        self.scroll_area = ScrollableArea(self)
        self.scroll_area.pack(fill='both', expand=True)
        self.canvas, self.inner = self.scroll_area.canvas, self.scroll_area.content

    def count(self, category):
        return len(self.grouped.get(category.key, [])) + sum(self.count(child) for child in category.children)

    def rebuild(self):
        position = self.canvas.yview()
        for child in self.inner.winfo_children():
            child.destroy()
        self.item_rows = {}
        self.category_rows = {}
        self.highlighted = None
        self.grouped = {}
        query = self.owner.search.get().strip().casefold()
        for item in self.items:
            if not query or query in item.instance.casefold() or query in item.title.casefold():
                self.grouped.setdefault(self.owner.location(item), []).append(item)
        count = sum(len(items) for items in self.grouped.values())
        self.heading.config(text=tr('app.items') + f' [{count}]')
        for category in self.owner.categories():
            if not query or self.count(category):CategoryRow(self, self.inner, category, 0)
        for item in self.grouped.get('', []):self.row_item(self.inner, item, 0)
        if query and not count:
            label(self.inner,'Ничего не найдено',fg=MUTED).pack(padx=12,pady=15)
        self.canvas.yview_moveto(position[0] if position else 0)

    def row_item(self, parent, item, level):
        selected = self.owner.is_selected(item)
        color = '#3a4d66' if selected else PANEL
        row = tk.Frame(parent, bg=color, height=31, cursor='hand2')
        row.pack(fill='x', padx=5, pady=1)
        row.pack_propagate(False)
        label(row, '', bg=color, width=level * 2).pack(side='left')
        badge = label(row, '?' if item.origin == 'project' else '?', bg=color,
                      fg='#7bd5a9' if item.origin == 'project' else MUTED)
        badge.pack(side='left', padx=(0, 6))
        title = label(row, item.title, bg=color, anchor='w', font=('Arial', 10))
        title.pack(side='left', fill='x', expand=True)
        row.item,row.title_label=item,title
        self.item_rows[self.owner.item_key(item)] = row
        if selected:self.highlighted=self.owner.item_key(item)
        for widget in (row, badge, title):
            widget.bind('<Button-1>', lambda event, r=row: self.owner.press_item(event,r.item))
            widget.bind('<B1-Motion>',self.owner.drag_motion)
            widget.bind('<ButtonRelease-1>',self.owner.release_item)
            widget.bind('<Double-Button-1>', lambda _, r=row, t=title: self.owner.rename(r.item, r, t))
            widget.bind('<Button-3>', lambda event, r=row: self.owner.context(event, r.item))
        return row

    def highlight(self):
        selected = self.owner.selection_keys()
        previous = getattr(self,'highlighted_keys',set())
        if self.highlighted is not None:previous = previous | {self.highlighted}
        for key in previous | selected:
            row = self.item_rows.get(key)
            if row is None:continue
            color = '#3a4d66' if key in selected else PANEL
            row.config(bg=color)
            for widget in row.winfo_children():widget.config(bg=color)
        self.highlighted_keys = set(selected)
        self.highlighted = self.owner.selected


class HierarchyPanel(Panel):
    def __init__(self, parent, on_select, on_create, on_duplicate, on_delete, on_rename, on_copy=None, on_export_model=None, on_export_texture=None):
        super().__init__(parent, bg=PANEL)
        self.on_select = on_select
        self.on_create = on_create
        self.on_duplicate = on_duplicate
        self.on_delete = on_delete
        self.on_rename = on_rename
        self.on_copy = on_copy or on_duplicate
        self.on_export_model = on_export_model
        self.on_export_texture = on_export_texture
        self.multiple = set()
        self.before_select = lambda: True
        self.on_multiple = None
        self.on_batch = None
        self._drag = None
        self.drag_preview = None
        self.drop_target = None
        self.store = None
        self.on_node = None
        self.on_node_action = None
        self.on_move = None
        self.selected_node = None
        self.items = []
        self.selected = None
        self._context_menu = None
        self.expanded = {}
        self.icons = IconImages.shared(self)
        self.arrow_frames = self.icons.frames('arrow_right.png', 18, MUTED, PANEL, steps=13)
        self.search = tk.StringVar(self)
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill='x', padx=12, pady=(12, 8))
        label(top, tr('hierarchy.title'), font=('Arial', 10, 'bold')).pack(side='left')
        search = make_entry(self, textvariable=self.search)
        search.pack(fill='x', padx=10, pady=(0, 10), ipady=6)
        self.search.trace_add('write', lambda *_: self.rebuild())
        self.panes = tk.PanedWindow(self, orient='vertical', bg=BG, bd=0, sashwidth=6)
        self.panes.pack(fill='both', expand=True)
        self.sections = {}
        for origin in ('project',):
            section = HierarchySection(self, self.panes, origin)
            self.sections[origin] = section
            self.panes.add(section, minsize=90, stretch='always')
        self.rebuild()
        owner=self.winfo_toplevel()
        self._shortcuts=[(sequence,owner.bind(sequence,self.shortcut,add='+'))
                         for sequence in ('<Control-KeyPress>','<Delete>')]
        self._shortcuts.append(('<Escape>',owner.bind('<Escape>',self.cancel_drag,add='+')))
        self.bind('<Destroy>',self.dispose,add='+')

    def dispose(self,event):
        if event.widget is self:
            self.cancel_drag()
            for sequence,binding in self._shortcuts:self.winfo_toplevel().unbind(sequence,binding)

    def shortcut(self,event):
        focused=self.focus_get()
        if focused is None or isinstance(focused,(tk.Entry,tk.Text,tk.Spinbox)):return
        if focused is not self and not str(focused).startswith(str(self)+'.'):return
        if len(self.selection_keys())>1:
            action = 'delete' if event.keysym=='Delete' else 'duplicate' if (
                event.keysym.lower() in ('d','cyrillic_ve') or event.keycode==68) else None
            if action in self.common_actions():self.on_batch(action,self.selected_values())
            return 'break' if action else None
        item=next((item for item in self.items if self.item_key(item)==self.selected),None)
        if item is None or item.origin!='project' or classify(item) not in EDITABLE_CATEGORIES:return
        if event.keysym=='Delete':self.on_delete(item)
        elif (event.keysym.lower() in ('d','cyrillic_ve') or
              (event.keycode==68 and self.tk.call('tk','windowingsystem')=='win32')):
            self.on_duplicate(item)
        else:return
        return 'break'

    @staticmethod
    def item_key(item):
        return item.origin, item.instance.casefold()

    def wheel(self, event):
        for section in self.sections.values():
            if section.scroll_area.wheel(event)=='break':return 'break'

    def set_items(self, items):
        self.items = items
        for origin, section in self.sections.items():
            section.items = list(items)
        self.rebuild()

    def update_item(self, previous, updated, items):
        query=self.search.get().strip().casefold()
        matches=lambda item:not query or query in item.instance.casefold() or query in item.title.casefold()
        structural=(self.item_key(previous)!=self.item_key(updated) or classify(previous)!=classify(updated)
                    or matches(previous)!=matches(updated))
        self.items=items
        for section in self.sections.values():
            section.items=list(items)
            if structural:
                section.rebuild()
                continue
            row=section.item_rows.get(self.item_key(previous))
            if row is not None:
                row.item=updated
                if previous.title!=updated.title:row.title_label.config(text=updated.title)
            category=self.location(updated)
            if category in section.grouped:
                section.grouped[category]=[updated if self.item_key(item)==self.item_key(previous) else item
                                           for item in section.grouped[category]]

    def insert_item(self,item,items):
        """Insert a new row without rebuilding unrelated categories or items."""
        self.items=items
        query=self.search.get().strip().casefold()
        category=self.location(item)
        for section in self.sections.values():
            section.items=list(items)
            if query and query not in item.title.casefold() and query not in item.instance.casefold():continue
            group=section.category_rows.get(category)
            if group is None:
                section.rebuild()
                continue
            siblings=section.grouped.setdefault(category,[])
            siblings.append(item)
            siblings.sort(key=lambda value:(value.title.casefold(),value.instance.casefold()))
            if group.built:
                row=section.row_item(group.content,item,group.level+1)
                index=siblings.index(item)
                if index+1<len(siblings):
                    following=section.item_rows.get(self.item_key(siblings[index+1]))
                    if following is not None:row.pack_configure(before=following)
            count=sum(len(values) for values in section.grouped.values())
            section.heading.config(text=tr('app.items')+f' [{count}]')
            for row in section.category_rows.values():
                row.title_label.config(text=self.category_title(row.category)+f' [{section.count(row.category)}]')

    def collapse_all(self):
        self.cancel_drag()
        self.multiple.clear()
        self.expanded.clear()
        self.selected = None
        self.selected_node = None
        self.search.set('')

    def choose(self, item):
        self.multiple.clear()
        self.selected_node = None
        self.selected = self.item_key(item) if item else None
        changed=self.reveal(item)
        if changed:self.rebuild()
        else:
            for section in self.sections.values():section.highlight()

    def reveal(self,item):
        changed=False
        if item:
            category = self.location(item)
            def reveal(nodes):
                nonlocal changed
                for node in nodes:
                    if node.key == category or reveal(node.children):
                        if not self.expanded.get(('project',node.key)):changed=True
                        self.expanded[('project', node.key)] = True
                        return True
                return False
            reveal(self.categories())
        return changed

    def rebuild(self):
        if hasattr(self, 'sections'):
            for section in self.sections.values():
                section.rebuild()

    def select(self, item):
        if not self.before_select():return False
        self.multiple.clear()
        self.selected_node = None
        self.selected = self.item_key(item)
        for section in self.sections.values():
            section.highlight()
        for section in self.sections.values():
            for row in section.category_rows.values():row.set_hover(False)
        self.on_select(item)

    def rename(self, item, row, title):
        if len(self.selection_keys())>1:return
        if classify(item) not in EDITABLE_CATEGORIES:return
        title.pack_forget()
        entry = make_entry(row, font=('Arial', 10))
        entry.insert(0, item.title)
        entry.pack(side='left', fill='x', expand=True)
        entry.focus_set()
        entry.select_range(0, 'end')
        done = False
        def commit(_=None):
            nonlocal done
            if done:
                return
            done = True
            value = entry.get().strip()
            if value and value != item.title:
                self.on_rename(item, value)
            else:
                self.rebuild()
        def cancel(_=None):
            nonlocal done
            done = True
            self.rebuild()
        entry.bind('<Return>', commit)
        entry.bind('<Escape>', cancel)

    def context(self, event, item):
        if self.multi_context(event,item):return
        if self.multiple and self.select(item) is False:return
        self.multiple.clear()
        self.selected_node = None
        self.focus_set()
        self.selected=self.item_key(item)
        for section in self.sections.values():section.highlight()
        if self._context_menu is not None:
            self._context_menu.destroy()
        menu = tk.Menu(self, tearoff=False, bg=INPUT, fg=TXT)
        self._context_menu = menu
        state='normal' if classify(item) in EDITABLE_CATEGORIES else 'disabled'
        if item.origin == 'project':
            menu.add_command(label=tr('hierarchy.duplicate'), accelerator='Ctrl+D',state=state, command=lambda: self.on_duplicate(item))
            menu.add_command(label=tr('hierarchy.delete'), accelerator='Delete',state=state, command=lambda: self.on_delete(item))
        else:
            menu.add_command(label=tr('hierarchy.copy_to_project'), state=state, command=lambda: self.on_copy(item))
        if self.store is not None and self.on_move is not None:
            move = tk.Menu(menu, tearoff=False, bg=INPUT, fg=TXT)
            move.add_command(label='В исходную категорию', command=lambda:self.on_move(item,''))
            def targets(nodes, path=''):
                for node in nodes:
                    title = path + node.name
                    if self.store.accepts(node.key,item):
                        move.add_command(label=title, command=lambda key=node.key:self.on_move(item,key))
                    targets(node.children,title+' / ')
            targets(self.categories())
            menu.add_cascade(label='Переместить в группу',menu=move)
        if self.on_export_model is not None:
            downloads=tk.Menu(menu,tearoff=False,bg=INPUT,fg=TXT)
            downloads.add_command(label='Модель 3DS',command=lambda:self.on_export_model(item))
            if self.on_export_texture is not None:
                downloads.add_command(label='Текстура',command=lambda:self.on_export_texture(item))
            menu.add_cascade(label='Скачать',menu=downloads)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def categories(self):return self.store.tree() if self.store else CATEGORIES

    def location(self, item):return self.store.location(item) if self.store else classify(item)

    def category_title(self, category):
        return category.name if isinstance(category, HierarchyNode) else tr('categories.' + category.key)

    def select_node(self, node):
        if self.on_node is None or not self.on_node(node):return False
        self.multiple.clear()
        self.selected = None
        self.selected_node = node.key
        for section in self.sections.values():
            section.highlight()
            for row in section.category_rows.values():row.set_hover(False)
        return True

    def context_node(self, event, node):
        if self.multi_context(event,node):return
        if self.store is None or not self.select_node(node):return
        if self._context_menu is not None:self._context_menu.destroy()
        menu = tk.Menu(self, tearoff=False, bg=INPUT, fg=TXT)
        self._context_menu = menu
        for title, action in [('Создать группу','create'), ('Дублировать','duplicate'),
                              ('Переименовать','rename'), ('Удалить','delete')]:
            menu.add_command(label=title, command=lambda a=action:self.on_node_action(a,node))
        if node.source in EDITABLE_CATEGORIES:
            menu.add_separator()
            menu.add_command(label='Добавить предмет', command=lambda:self.on_node_action('add',node))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def selection_keys(self):
        if self.multiple:return set(self.multiple)
        if self.selected_node is not None:return {('node',self.selected_node)}
        return {self.selected} if self.selected is not None else set()

    def value_key(self,value):
        return ('node',value.key) if isinstance(value,Category) else self.item_key(value)

    def is_selected(self,value):return self.value_key(value) in self.selection_keys()

    def selected_values(self):
        from gothic_editor.core.categories import walk_categories
        keys = self.selection_keys()
        return [value for value in [*walk_categories(self.categories()),*self.items]
                if self.value_key(value) in keys]

    def paint_selection(self):
        for section in self.sections.values():
            section.highlight()
            for row in section.category_rows.values():row.set_hover(False)

    def toggle_selection(self,value):
        if self.store is None:return False
        if not self.before_select():return False
        keys = self.selection_keys()
        key = self.value_key(value)
        if key in keys:keys.remove(key)
        else:keys.add(key)
        self.multiple = keys
        self.selected = self.selected_node = None
        values = self.selected_values()
        if len(values)==1:
            value = values[0]
            if isinstance(value,Category):self.select_node(value)
            else:self.select(value)
        elif self.on_multiple is not None:self.on_multiple()
        self.focus_set()
        self.paint_selection()
        return True

    def common_actions(self):
        values = self.selected_values()
        common = None
        for value in values:
            if isinstance(value,Category):actions = {'duplicate','delete'}
            else:
                actions = {'move'}
                if classify(value) in EDITABLE_CATEGORIES:
                    actions |= {'duplicate','delete'} if value.origin=='project' else {'copy'}
            common = actions if common is None else common & actions
        return common or set()

    def multi_context(self,event,value):
        if len(self.selection_keys())<2 or not self.is_selected(value):return False
        self.focus_set()
        if self._context_menu is not None:self._context_menu.destroy()
        menu = tk.Menu(self,tearoff=False,bg=INPUT,fg=TXT)
        self._context_menu = menu
        values = self.selected_values()
        actions = self.common_actions()
        for action,title in [('duplicate','Дублировать'),('delete','Удалить'),('copy','Копировать в проект')]:
            if action in actions:
                menu.add_command(label=title,command=lambda a=action:self.on_batch(a,values))
        if 'move' in actions and self.store is not None:
            move = tk.Menu(menu,tearoff=False,bg=INPUT,fg=TXT)
            move.add_command(label='В исходные категории',command=lambda:self.on_batch('move',values,''))
            def targets(nodes,path=''):
                for node in nodes:
                    title = path + node.name
                    if all(self.store.accepts(node.key,item) for item in values):
                        move.add_command(label=title,command=lambda key=node.key:self.on_batch('move',values,key))
                    targets(node.children,title+' / ')
            targets(self.categories())
            menu.add_cascade(label='Переместить',menu=move)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return True

    def press_item(self,event,item):
        self.cancel_drag()
        if event.state & 1:
            self.toggle_selection(item)
            return
        if not self.is_selected(item):
            if self.select(item) is False:return
        self.focus_set()
        self._drag = (event.x_root,event.y_root,item,False)

    def press_node(self,event,node):
        self.cancel_drag()
        if event.state & 1:
            self.toggle_selection(node)
            return
        if not self.is_selected(node) and not self.select_node(node):return
        self.focus_set()
        self._drag = (event.x_root,event.y_root,node,False)

    def drop_at(self,x,y):
        widget = self.winfo_containing(x,y)
        for section in self.sections.values():
            if widget in (section.inner,section.canvas):return ''
            for key,row in section.category_rows.items():
                if widget is row.header or widget in row.header.winfo_children():return key
        return None

    def drag_motion(self,event):
        if self._drag is None:return
        x,y,value,moved = self._drag
        if not moved and abs(event.x_root-x)+abs(event.y_root-y)<=6:return
        self._drag = (x,y,value,True)
        values = self.selected_values()
        target = self.drop_at(event.x_root,event.y_root)
        allowed = target is not None and self.store is not None and self.store.can_move(values,target)
        self.drop_target = (target,allowed)
        self.paint_selection()
        if self.drag_preview is None:
            from gothic_editor.ui.widgets.drag_preview import DragPreview
            self.drag_preview = DragPreview(self,[value.name if isinstance(value,Category) else value.title
                                                  for value in values])
        title = self.store.title(self.store.row(target)) if target else 'В исходные категории'
        self.drag_preview.move(event.x_root,event.y_root,title,allowed)

    def cancel_drag(self,event=None):
        active = self._drag is not None
        self._drag = None
        self.drop_target = None
        if self.drag_preview is not None:
            self.drag_preview.destroy()
            self.drag_preview = None
        for section in getattr(self,'sections',{}).values():
            for row in section.category_rows.values():
                if row.winfo_exists():row.set_hover(False)
        if active and event is not None:return 'break'

    def release_item(self,event):
        drag = self._drag
        if drag is None:return
        values = self.selected_values()
        target = self.drop_at(event.x_root,event.y_root) if drag[3] else None
        allowed = (drag[3] and target is not None and self.store is not None
                   and self.store.can_move(values,target))
        self.cancel_drag()
        if not drag[3]:
            if isinstance(drag[2],Category):
                if not self.select_node(drag[2]):return
                for section in self.sections.values():
                    row = section.category_rows.get(drag[2].key)
                    if row is not None:row.toggle()
            elif len(self.selection_keys())>1:self.select(drag[2])
            return
        if allowed and self.on_batch is not None:self.on_batch('move',values,target)
