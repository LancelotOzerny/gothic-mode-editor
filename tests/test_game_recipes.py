import tempfile
import unittest
from pathlib import Path
from gothic_editor.core.game_recipes import game_recipes


SOURCE = '''func void PC_PotionAlchemy_End_Info() {CreateInvItems(self, ItMi_Flask,1);};
instance PC_Test(C_Info) {condition=Cond; information=Info; description="Essence";};
func int Cond() {if (HealthStart == TRUE) {return TRUE;};};
func void Info() {
 if (Npc_HasItems(hero, HERB)>=2) {
 Npc_RemoveInvItems(hero, HERB,2);
 CreateInvItem(hero, POTION);
 Print(PRINT_AlchemySuccess);
 } else {Print(PRINT_ProdItemsMissing); CreateInvItems(self, ItMi_Flask,1);};
 B_ENDPRODUCTIONDIALOG();
};'''


class GameRecipeTests(unittest.TestCase):
    def test_template_counts_flask_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            path = game/'_work/Data/Scripts/Content/Potion_Alchemy.d'
            path.parent.mkdir(parents=True)
            path.write_text(SOURCE, 'cp1251')
            rows, skipped = game_recipes(game)
            self.assertFalse(skipped)
            self.assertEqual(rows[0]['category'], 'health')
            self.assertEqual(rows[0]['result'], 'POTION')
            self.assertEqual(rows[0]['ingredients'], [{'instance':'HERB', 'count':2}, {'instance':'ItMi_Flask', 'count':1}])
            self.assertEqual(path.read_text('cp1251'), SOURCE)
            path.write_text(SOURCE.replace('CreateInvItem(hero, POTION);', 'CreateInvItem(hero, POTION); ExtraEffect();'), 'cp1251')
            rows, skipped = game_recipes(game)
            self.assertFalse(rows)
            self.assertEqual(skipped, ['pc_test'])

    def test_missing_sources_are_reported(self):
        with self.assertRaises(ValueError):game_recipes(None)
