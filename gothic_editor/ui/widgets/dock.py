"""Extensible, independently enabled tabs for the bottom workspace dock."""
import tkinter as tk
from tkinter import ttk
from .theme import BG, BORDER, HOVER_BG, INPUT, PANEL, TXT

TAB_ACTION_HEIGHT = 24


class BottomDock(ttk.Notebook):
    def __init__(self, parent):
        style = ttk.Style(parent)
        if 'BottomDock.client' not in style.element_names():
            style.element_create('BottomDock.client', 'from', 'clam', 'Notebook.client')
            style.element_create('BottomDock.tab', 'from', 'clam', 'Notebook.tab')
        style.layout('BottomDock.TNotebook', [('BottomDock.client', {'sticky': 'nswe'})])
        style.layout('BottomDock.TNotebook.Tab', [('BottomDock.tab', {'sticky': 'nswe', 'children': [
            ('Notebook.padding', {'sticky': 'nswe', 'children': [('Notebook.label', {'sticky': 'nswe'})]})]})])
        colors = dict(bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.configure('BottomDock.TNotebook', background=BG, borderwidth=1, **colors)
        style.configure('BottomDock.TNotebook.Tab', background=INPUT, foreground=TXT, padding=(12, 5), **colors)
        style.map('BottomDock.TNotebook.Tab', background=[('selected', PANEL), ('active', HOVER_BG)])
        super().__init__(parent, style='BottomDock.TNotebook')
        self.panels = {}
        self.toolbars = {}
        self.bind('<<NotebookTabChanged>>', self._show_actions, add='+')

    def register(self, key, title, panel):
        if key in self.panels:
            raise ValueError(f'Duplicate dock tab: {key}')
        self.panels[key] = panel
        build_actions = getattr(panel, 'build_tab_actions', None)
        if build_actions is not None:
            toolbar = tk.Frame(self, bg=BG)
            build_actions(toolbar)
            self.toolbars[key] = toolbar
            panel.bind('<Configure>', self._show_actions, add='+')
        self.add(panel, text=title, state='hidden')
        self.hide(panel)  # Tk may automatically enable the notebook's first tab.

    def set_visible(self, key, visible):
        panel = self.panels[key]
        self.tab(panel, state='normal' if visible else 'hidden')
        if visible:
            self.select(panel)
        self._show_actions()

    def _show_actions(self, _event=None):
        selected = self.selected_key()
        for key, toolbar in self.toolbars.items():
            if key == selected:
                tab_height = max(TAB_ACTION_HEIGHT, self.panels[key].winfo_y())
                toolbar.place(relx=1, x=-4, y=tab_height // 2, anchor='e')
                toolbar.lift()
            else:
                toolbar.place_forget()

    def visible_keys(self):
        return [key for key, panel in self.panels.items() if self.tab(panel, 'state') != 'hidden']

    def selected_key(self):
        selected = self.select()
        return next((key for key, panel in self.panels.items() if str(panel) == selected), None)
