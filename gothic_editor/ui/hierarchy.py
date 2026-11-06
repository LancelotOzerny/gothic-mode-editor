"""Project hierarchy with lazy category rows and animated disclosure icons."""
from __future__ import annotations

import tkinter as tk
from time import monotonic

from ..core.categories import CATEGORIES, classify
from ..core.localization import tr
from .icons import IconImages
from .widgets import BG, PANEL, INPUT, TXT, MUTED, ACCENT, label, make_entry


class CategoryRow(tk.Frame):
    def __init__(self, section, parent, category, level):
        super().__init__(parent, bg=PANEL)
        self.section = section
        self.category = category
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
        label(row, category.icon, fg=ACCENT, font=('Segoe UI Symbol', 13)).pack(side='left', padx=(0, 5))
        title = label(row, tr('categories.' + category.key) + f' [{section.count(category)}]',
                      font=('Arial', 10, 'bold'), anchor='w')
        title.pack(side='left', fill='x', expand=True)
        title.bind('<Button-1>', lambda _: self.toggle())
        if section.origin == 'project':
            plus = tk.Label(row, text='+', bg=INPUT, fg=ACCENT, font=('Arial', 14, 'bold'),
                            width=2, cursor='hand2')
            plus.pack(side='right', padx=5)
            plus.bind('<Button-1>', lambda _: section.owner.on_create(category.key))
        self.content = tk.Frame(self, bg=PANEL)
        if self.opened:
            self.show_content()
        self.bind('<Destroy>', self.cancel_animation, add='+')

    def show_content(self):
        if not self.built:
            for child in self.category.children:
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


class HierarchySection(tk.Frame):
    def __init__(self, owner, parent, origin):
        super().__init__(parent, bg=PANEL)
        self.owner = owner
        self.origin = origin
        self.items = []
        self.grouped = {}
        self.item_rows = {}
        self.heading = label(self, '', fg=ACCENT, anchor='w', font=('Arial', 10, 'bold'))
        self.heading.pack(fill='x', padx=10, pady=8)
        scroll = tk.Scrollbar(self, orient='vertical')
        scroll.pack(side='right', fill='y')
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, yscrollcommand=scroll.set)
        self.canvas.pack(fill='both', expand=True)
        scroll.config(command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=PANEL)
        item = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda _: self.canvas.config(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(item, width=event.width))

    def count(self, category):
        return len(self.grouped.get(category.key, [])) + sum(self.count(child) for child in category.children)

    def rebuild(self):
        position = self.canvas.yview()
        for child in self.inner.winfo_children():
            child.destroy()
        self.item_rows = {}
        self.grouped = {}
        query = self.owner.search.get().strip().casefold()
        for item in self.items:
            if not query or query in item.instance.casefold() or query in item.title.casefold():
                self.grouped.setdefault(classify(item), []).append(item)
        count = sum(len(items) for items in self.grouped.values())
        self.heading.config(text=tr('hierarchy.project' if self.origin == 'project' else 'hierarchy.original') + f' [{count}]')
        for category in CATEGORIES:
            CategoryRow(self, self.inner, category, 0)
        self.canvas.yview_moveto(position[0] if position else 0)

    def row_item(self, parent, item, level):
        selected = self.owner.selected == self.owner.item_key(item)
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
        self.item_rows[self.owner.item_key(item)] = row
        for widget in (row, badge, title):
            widget.bind('<Button-1>', lambda _, current=item: self.owner.select(current))
            widget.bind('<Double-Button-1>', lambda _, current=item, r=row, t=title: self.owner.rename(current, r, t))
            widget.bind('<Button-3>', lambda event, current=item: self.owner.context(event, current))

    def highlight(self):
        for key, row in self.item_rows.items():
            color = '#3a4d66' if key == self.owner.selected else PANEL
            row.config(bg=color)
            for widget in row.winfo_children():
                widget.config(bg=color)


class HierarchyPanel(tk.Frame):
    def __init__(self, parent, on_select, on_create, on_duplicate, on_delete, on_rename, on_copy=None, on_export_model=None):
        super().__init__(parent, bg=PANEL)
        self.on_select = on_select
        self.on_create = on_create
        self.on_duplicate = on_duplicate
        self.on_delete = on_delete
        self.on_rename = on_rename
        self.on_copy = on_copy or on_duplicate
        self.on_export_model = on_export_model
        self.items = []
        self.selected = None
        self._context_menu = None
        self.expanded = {}
        self.icons = IconImages(self)
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
        self.bind('<MouseWheel>', self.wheel)
        # Descendants inherit the root bind tag, so scope wheel events to this panel.
        self.root = self.winfo_toplevel()
        self._wheel_binding = self.root.bind('<MouseWheel>', self.wheel, add='+')
        self.bind('<Destroy>', self._destroy, add='+')
        self.rebuild()

    @staticmethod
    def item_key(item):
        return item.origin, item.instance.casefold()

    def wheel(self, event):
        for section in self.sections.values():
            canvas = section.canvas
            if (canvas.winfo_rootx() <= event.x_root < canvas.winfo_rootx() + canvas.winfo_width()
                    and canvas.winfo_rooty() <= event.y_root < canvas.winfo_rooty() + canvas.winfo_height()):
                canvas.yview_scroll(-int(event.delta / 120), 'units')
                return 'break'

    def _destroy(self, event):
        # The root callback must not retain a destroyed panel after language changes.
        if event.widget is self and self._wheel_binding:
            self.root.unbind('<MouseWheel>', self._wheel_binding)

    def set_items(self, items):
        self.items = items
        for origin, section in self.sections.items():
            section.items = [item for item in items if item.origin == origin]
        self.rebuild()

    def collapse_all(self):
        self.expanded.clear()
        self.selected = None
        self.search.set('')

    def choose(self, item):
        self.selected = self.item_key(item) if item else None
        if item:
            category = classify(item)
            def reveal(nodes):
                for node in nodes:
                    if node.key == category or reveal(node.children):
                        self.expanded[(item.origin, node.key)] = True
                        return True
                return False
            reveal(CATEGORIES)
        self.rebuild()

    def rebuild(self):
        if hasattr(self, 'sections'):
            for section in self.sections.values():
                section.rebuild()

    def select(self, item):
        self.selected = self.item_key(item)
        for section in self.sections.values():
            section.highlight()
        self.on_select(item)

    def rename(self, item, row, title):
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
        if self._context_menu is not None:
            self._context_menu.destroy()
        menu = tk.Menu(self, tearoff=False, bg=INPUT, fg=TXT)
        self._context_menu = menu
        if item.origin == 'project':
            menu.add_command(label=tr('hierarchy.duplicate'), command=lambda: self.on_duplicate(item))
            menu.add_command(label=tr('hierarchy.delete'), command=lambda: self.on_delete(item))
        else:
            menu.add_command(label=tr('hierarchy.copy_to_project'), command=lambda: self.on_copy(item))
        if self.on_export_model is not None:
            menu.add_command(label=tr('hierarchy.download_model_3ds'), command=lambda: self.on_export_model(item))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
