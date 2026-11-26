"""Small shared command registry for context menus and keyboard shortcuts."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class UIAction:
    key: str
    label: str
    execute: Callable
    enabled: Callable = lambda: True
    accelerator: str = ''


class ActionRegistry:
    def __init__(self):
        self._actions = {}

    def register(self, key, label, execute, *, enabled=lambda: True, accelerator=''):
        self._actions[key] = UIAction(key, label, execute, enabled, accelerator)
        return self._actions[key]

    def get(self, key):
        return self._actions[key]

    def invoke(self, key):
        action = self.get(key)
        if not action.enabled():
            return False
        action.execute()
        return True

    def add_to_menu(self, menu, key):
        action = self.get(key)
        menu.add_command(label=action.label, accelerator=action.accelerator,
                         state='normal' if action.enabled() else 'disabled',
                         command=lambda: self.invoke(key))
