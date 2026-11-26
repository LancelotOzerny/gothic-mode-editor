"""Event dispatch and incremental update regression tests without Gothic assets."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gothic_editor.ui.events import UIEvent
from gothic_editor.app import EditorApp
from gothic_editor.ui.panels.recipes import RecipeListPanel
from gothic_editor.ui.panels.world import WorldPanel


class PanelEventTests(unittest.TestCase):
    def test_npc_property_change_updates_one_row(self):
        npc=SimpleNamespace(instance='NPC_A',title='Updated')
        app=SimpleNamespace(npcs=SimpleNamespace(show_list=Mock()),
                            world_panel=SimpleNamespace(update_npc=Mock()))
        EditorApp._on_npc_event(app,UIEvent('npc.changed',(npc,False)))
        app.world_panel.update_npc.assert_called_once_with(npc)
        app.npcs.show_list.assert_not_called()

    def test_npc_selection_change_rebuilds_only_list(self):
        app=SimpleNamespace(npcs=SimpleNamespace(show_list=Mock()),
                            world_panel=SimpleNamespace(update_npc=Mock()))
        EditorApp._on_npc_event(app,UIEvent('npc.changed',(None,True)))
        app.npcs.show_list.assert_called_once()
        app.world_panel.update_npc.assert_not_called()

    def test_recipe_change_updates_row_when_structure_is_unchanged(self):
        previous={'id':'recipe1','category':'alchemy','name':'Old'}
        updated={**previous,'name':'New'}
        app=SimpleNamespace(recipe_list=SimpleNamespace(update_recipe=Mock(),populate=Mock()))
        EditorApp._on_recipe_event(app,UIEvent('recipes.changed',(previous,updated,False)))
        app.recipe_list.update_recipe.assert_called_once_with(previous,updated)
        app.recipe_list.populate.assert_not_called()
        EditorApp._on_recipe_event(app,UIEvent('recipes.changed',(previous,updated,True)))
        app.recipe_list.populate.assert_called_once()

    def test_world_selection_changes_skip_repository_reindex(self):
        app=SimpleNamespace(world=SimpleNamespace(refresh=Mock(),catalog_stamp=123),
                            repo=SimpleNamespace(refresh=Mock()),
                            resources=SimpleNamespace(refresh=Mock()))
        EditorApp._on_world_event(app,UIEvent('world.changed',('selection',None)))
        app.world.refresh.assert_called_once()
        app.repo.refresh.assert_not_called()
        app.resources.refresh.assert_not_called()

    def test_world_model_change_invalidates_index(self):
        app=SimpleNamespace(world=SimpleNamespace(refresh=Mock(),catalog_stamp=123),
                            repo=SimpleNamespace(refresh=Mock()),
                            resources=SimpleNamespace(refresh=Mock()))
        EditorApp._on_world_event(app,UIEvent('world.changed',('model',None)))
        app.repo.refresh.assert_called_once()
        self.assertIsNone(app.world.catalog_stamp)
        app.world.refresh.assert_called_once()
        app.resources.refresh.assert_called_once()

    def test_recipe_row_update_does_not_rebuild_when_visible(self):
        previous={'id':'recipe1','category':'alchemy','name':'Old'}
        updated={**previous,'name':'New'}
        row=SimpleNamespace(winfo_exists=lambda:True,title_label=SimpleNamespace(configure=Mock()))
        panel=SimpleNamespace(search=SimpleNamespace(get=lambda:''),grouped={'alchemy':[previous]},
                              recipe_rows={'recipe1':row},populate=Mock())
        RecipeListPanel.update_recipe(panel,previous,updated)
        panel.populate.assert_not_called()
        row.title_label.configure.assert_called_once_with(text='New')
        self.assertEqual(panel.grouped['alchemy'],[updated])

    def test_world_unchanged_list_skips_rebuild(self):
        resource=SimpleNamespace(name='model.3ds')
        panel=SimpleNamespace(resources=[resource],npcs=[],rebuild=Mock(),search=SimpleNamespace(get=lambda:''),
                              selected=None,entries={},npc_entries={})
        WorldPanel.set_resources(panel,[resource],[])
        panel.rebuild.assert_not_called()
