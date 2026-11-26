"""UI event and action contracts independent of Tk's display server."""
import unittest
from unittest.mock import Mock

from gothic_editor.ui.events import EventBus, UIEvent
from gothic_editor.ui.actions import ActionRegistry


class EventBusTests(unittest.TestCase):
    def test_delivery_unsubscribe_and_mutation_during_publish(self):
        bus=EventBus()
        received=[]
        stop=None

        def once(event):
            received.append(('first',event.payload))
            stop()

        stop=bus.subscribe('resource.changed',once)
        bus.subscribe('resource.changed',lambda event:received.append(('second',event.payload)))
        result=bus.publish('resource.changed',('old','new'))
        self.assertEqual(result,UIEvent('resource.changed',('old','new')))
        bus.publish('resource.changed',('new','newer'))
        self.assertEqual(received,[('first',('old','new')),
                                   ('second',('old','new')),
                                   ('second',('new','newer'))])

    def test_events_are_isolated_by_name_and_by_bus(self):
        first=EventBus()
        second=EventBus()
        called=Mock()
        first.subscribe('items.changed',called)
        first.publish('resources.changed')
        second.publish('items.changed')
        called.assert_not_called()
        first.publish('items.changed',42)
        called.assert_called_once_with(UIEvent('items.changed',42))


class ActionRegistryTests(unittest.TestCase):
    def test_disabled_action_does_not_run_and_can_be_reenabled(self):
        state={'enabled':False}
        callback=Mock()
        actions=ActionRegistry()
        actions.register('delete','Удалить',callback,
                         enabled=lambda:state['enabled'],accelerator='Delete')
        self.assertFalse(actions.invoke('delete'))
        callback.assert_not_called()
        state['enabled']=True
        self.assertTrue(actions.invoke('delete'))
        callback.assert_called_once()
        self.assertEqual(actions.get('delete').accelerator,'Delete')

    def test_menu_uses_same_dispatch_as_shortcut(self):
        callback=Mock()
        actions=ActionRegistry()
        actions.register('copy','Копировать',callback)
        menu=Mock()
        actions.add_to_menu(menu,'copy')
        command=menu.add_command.call_args.kwargs['command']
        command()
        callback.assert_called_once()
