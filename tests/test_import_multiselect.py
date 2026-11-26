"""Bulk selection and native NPC model exports."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gothic_editor.ui.windows.value_choice import ValueChoiceWindow
from gothic_editor.ui.controllers.npc import NpcController


class MultiSelectTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.root.destroy)

    def test_picker_can_select_multiple_and_filter_without_losing_choices(self):
        selected=[]
        picker=ValueChoiceWindow(self.root,[('Sword','A'),('Potion','B'),('Shield','C')],
                                 -1,'Test',lambda indices:selected.extend(indices),
                                 lambda:None,searchable=True,multiple=True)
        self.addCleanup(lambda:picker.destroy() if picker.winfo_exists() else None)
        picker.focus_option(0,toggle=True)
        picker.focus_option(2,toggle=True)
        self.assertEqual(picker.chosen,{0,2})
        picker.query.set('Potion')
        self.assertEqual(picker.chosen,{0,2})
        picker.apply()
        self.assertEqual(selected,[0,2])

    def test_native_head_and_body_export_do_not_modify_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for kind,suffix in (('head','.mmb'),('body','.mdm')):
                source=root/('Original'+suffix)
                source.write_bytes(b'native-model-data-'+kind.encode())
                target=root/('Export'+suffix)
                fields={kind:SimpleNamespace(get=lambda:'Original')}
                app=SimpleNamespace(npc_properties=SimpleNamespace(fields=fields))
                controller=NpcController(app)
                controller.current=SimpleNamespace(instance='NPC_TEST')
                controller.save=lambda:True
                controller.index=SimpleNamespace(find=lambda name,extensions:source)
                with patch('gothic_editor.ui.controllers.npc.filedialog.asksaveasfilename',
                           return_value=str(target)):
                    controller.export_model(kind)
                self.assertEqual(target.read_bytes(),source.read_bytes())


if __name__=='__main__':
    unittest.main()
