"""Trading persistence and staged Daedalus integration tests."""
from pathlib import Path
import tempfile
import unittest

from gothic_editor.core.trading import TradingStore
from gothic_editor.core.trading_generator import prepare_trading, prioritize_trading, OUTPUT, DIALOG_OUTPUT
from gothic_editor.core.scripts import load_text


class TradingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.store = TradingStore(self.project)
        self.content = self.root / 'stage' / 'Content'
        self.content.mkdir(parents=True)
        (self.content / 'NPC.d').write_text(
            'instance NPC_Merchant(C_Npc) { name = "Merchant"; };\n'
            'instance ItFo_Bread(C_Item) { name = "Bread"; };\n',
            encoding='cp1251')
        (self.content / 'Trade.d').write_text(
            'func void B_GiveTradeInv(var C_Npc slf) { CreateInvItems(slf, ItFo_Bread, 2); };\n',
            encoding='cp1251')
        (self.content / 'Gothic.src').write_text(
            'NPC.d\nGE_Trading\\Stock.d\nTrade.d\n', encoding='cp1251')

    def config(self, **changes):
        result = dict(enabled=True, dialog=True, replace_original=False,
                      min_chapter=2, refresh_hours=24,
                      stock=[dict(item='ItFo_Bread', quantity=5, chapter=2)])
        result.update(changes)
        return result

    def test_roundtrip_disabled_and_validation(self):
        self.store.save('NPC_Merchant', self.config())
        self.assertEqual(self.store.read()['npc_merchant']['stock'][0]['quantity'], 5)
        for changes in (dict(refresh_hours=-1), dict(min_chapter=9),
                        dict(stock=[dict(item='Bad();',quantity=1,chapter=1)]),
                        dict(stock=[dict(item='ItFo_Bread',quantity=0,chapter=1)]),
                        dict(stock=[dict(item='ItFo_Bread',quantity=1,chapter=1),
                                    dict(item='itfo_bread',quantity=2,chapter=1)])):
            with self.assertRaises(ValueError):
                self.store.save('NPC_Merchant', self.config(**changes))
        self.assertEqual(len(self.store.read()), 1)
        self.store.save('NPC_Merchant', None)
        self.assertEqual(self.store.read(), {})

    def test_stage_preserves_source_and_generates_dialog_and_refresh(self):
        self.store.save('NPC_Merchant', self.config())
        original=(self.content / 'Trade.d').read_bytes()
        self.assertEqual(prepare_trading(self.project,self.content), [OUTPUT,DIALOG_OUTPUT])
        code,_ = load_text(self.content / OUTPUT)
        self.assertIn('GE_TradeDialog_NPC_MERCHANT', (self.content / DIALOG_OUTPUT).read_text('cp1251'))
        self.assertIn('Kapitel >= 2', code)
        self.assertIn('Wld_IsTime(geHour, 0, geEnd, 0)', code)
        self.assertNotIn('Wld_GetTime', code)
        self.assertIn('Npc_HasItems(slf, ItFo_Bread)', code)
        self.assertLess(code.index('var int geHour;'),code.index('if ((Kapitel >= 2)'))
        patched,_ = load_text(self.content / 'Trade.d')
        self.assertIn('GE_TradeStock_NPC_MERCHANT(slf);', patched)
        self.assertIn('CreateInvItems(slf, ItFo_Bread, 2);', patched)
        self.assertNotEqual((self.content / 'Trade.d').read_bytes(), original)
        manifest=self.content/'Gothic.src'
        prioritize_trading(manifest)
        lines=manifest.read_text('cp1251').splitlines()
        self.assertLess(lines.index('GE_Trading\\Stock.d'),lines.index('Trade.d'))

    def test_replace_original_and_missing_item(self):
        self.store.save('NPC_Merchant', self.config(replace_original=True,dialog=False))
        prepare_trading(self.project,self.content)
        text=(self.content/'Trade.d').read_text('cp1251')
        self.assertIn('return;', text)
        self.assertFalse((self.content/DIALOG_OUTPUT).exists())
        self.store.save('NPC_Merchant',self.config(stock=[dict(item='Missing',quantity=2,chapter=1)]))
        with self.assertRaisesRegex(ValueError,'Missing'):
            prepare_trading(self.project,self.content)


if __name__ == '__main__':
    unittest.main()
