"""Synchronous, instance-local events for incremental UI updates.

Subscribers run on the Tk thread that publishes an event. External threads must
schedule delivery with Tk.after; this bus never touches widgets itself.
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class UIEvent:
    name: str
    payload: Any = None


class EventBus:
    def __init__(self):
        self._listeners = defaultdict(list)

    def subscribe(self, name: str, callback: Callable):
        listeners = self._listeners[name]
        if callback not in listeners:
            listeners.append(callback)

        def unsubscribe():
            self.unsubscribe(name, callback)
        return unsubscribe

    def unsubscribe(self, name: str, callback: Callable):
        listeners = self._listeners.get(name)
        if listeners is None:
            return
        if callback in listeners:
            listeners.remove(callback)
        if not listeners:
            self._listeners.pop(name, None)

    def publish(self, name: str, payload=None):
        event = UIEvent(name, payload)
        # Snapshot permits a listener to unsubscribe while dispatching.
        for callback in tuple(self._listeners.get(name, ())):
            callback(event)
        return event
