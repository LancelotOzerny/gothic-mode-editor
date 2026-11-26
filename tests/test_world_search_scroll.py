"""World and NPC browser search should leave all long-list rows scrollable."""
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

from gothic_editor.core.world_resources import WorldResource
from gothic_editor.ui.panels.world import WorldPanel


class WorldSearchScrollTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.root.destroy)
        self.root.geometry('360x280')
        self.panel=WorldPanel(self.root,lambda resource:None,lambda npc:None)
        self.panel.pack(fill='both',expand=True)

    def test_all_world_rows_are_reachable_after_expanding_category(self):
        models=[WorldResource(f'House_{i:02}.3ds',Path(f'House_{i:02}.3ds'),
                              'architecture') for i in range(45)]
        self.panel.set_resources(models)
        self.panel.category_rows['architecture'].toggle()
        self.root.update()
        canvas=self.panel.area.canvas
        self.assertEqual(len(self.panel.rows),45)
        self.assertLess(canvas.yview()[1]-canvas.yview()[0],1)
        canvas.yview_moveto(1)
        self.root.update()
        self.assertGreater(canvas.yview()[0],0)
        self.panel.search.set('house_44')
        self.root.update()
        self.assertEqual(list(self.panel.entries),['model:house_44.3ds'])

    def test_npc_search_uses_instance_body_and_head(self):
        npcs=[SimpleNamespace(instance=f'NPC_{i:02}',title=f'Guard {i}',
                body=f'HUM_BODY_{i:02}',head=f'HUM_HEAD_{i:02}',
                overridden=False) for i in range(12)]
        self.panel.set_resources([],npcs)
        self.panel.search.set('HUM_HEAD_11')
        self.root.update()
        self.assertEqual(list(self.panel.npc_entries),['npc:npc_11'])


if __name__=='__main__':
    unittest.main()
