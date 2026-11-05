"""Extensible, independently enabled tabs for the bottom workspace dock."""
from tkinter import ttk


class BottomDock(ttk.Notebook):
    def __init__(self, parent):
        super().__init__(parent)
        self.panels = {}

    def register(self, key, title, panel):
        if key in self.panels:
            raise ValueError(f'Duplicate dock tab: {key}')
        self.panels[key] = panel
        self.add(panel, text=title, state='hidden')
        self.hide(panel)  # Tk may automatically enable the notebook's first tab.

    def set_visible(self, key, visible):
        panel = self.panels[key]
        self.tab(panel, state='normal' if visible else 'hidden')
        if visible:
            self.select(panel)

    def visible_keys(self):
        return [key for key, panel in self.panels.items() if self.tab(panel, 'state') != 'hidden']

    def selected_key(self):
        selected = self.select()
        return next((key for key, panel in self.panels.items() if str(panel) == selected), None)
