"""XLSX menus, responsive modal operations, errors, and selection refresh on synthetic data."""
from pathlib import Path
from time import monotonic,sleep
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.settings import SettingsStore
from gothic_editor.core.xlsx import write_table,read_table
from test_spreadsheets import synthetic_schema


class SpreadsheetWindowTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        patcher=patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(self.root/'settings.json'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app=EditorApp()
        self.addCleanup(self.app.destroy)
        for module in ('gothic_editor.ui.panels.properties','gothic_editor.core.item_spreadsheet'):
            patcher=patch(module+'.schema_for',side_effect=synthetic_schema)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app.repo.create(self.root/'project','Spreadsheet')
        self.item=self.app.repo.create_item_from_fields('ItPo_Test',{'name':'"Before"','mainflag':'ITEM_KAT_POTIONS','value':'1'})
        self.app.show_project()
        self.app.hierarchy.choose(self.item)
        self.app.select(self.item)
        self.app.update()
        self.errors=[]
        self.app.report_callback_exception=lambda *error:self.errors.append(error)

    def finish(self,window):
        deadline=monotonic()+8
        while window.runner.running and monotonic()<deadline:
            self.app.update()
            sleep(.005)
        self.assertFalse(window.runner.running)
        self.assertEqual(self.errors,[])

    def test_export_menu_modal_file_selection_progress_and_focused_draft(self):
        field=self.app.properties.inputs['name']
        field.delete(0,'end')
        field.insert(0,'Changed while focused')
        main=self.app.main_menu
        project_index=next(index for index in range(main.index('end')+1)
                           if main.type(index)=='cascade' and main.entrycget(index,'label')=='Проект')
        project=main.nametowidget(main.entrycget(project_index,'menu'))
        index=next(index for index in range(project.index('end')+1) if project.entrycget(index,'label')=='Экспорт')
        submenu=project.nametowidget(project.entrycget(index,'menu'))
        self.assertEqual(submenu.entrycget(0,'label'),'xlsx')
        submenu.invoke(0)
        window=self.app.spreadsheet_window
        self.app.update()
        self.assertIs(self.app.grab_current(),window)
        destination=self.root/'exported.xlsx'
        with patch('gothic_editor.ui.windows.spreadsheet.filedialog.asksaveasfilename',return_value=str(destination)):
            window.browse()
        window.start()
        self.finish(window)
        self.assertEqual(window.progress_bar.value,1)
        rows=read_table(destination)
        self.assertEqual(rows[1][rows[0].index('name')],'"Changed while focused"')
        self.assertIn('Экспортировано предметов: 1',window.status.cget('text'))
        self.assertLess(window.progress_bar.winfo_rooty()+window.progress_bar.winfo_height(),window.winfo_rooty()+window.winfo_height())
        window.close()
        self.assertFalse(window.winfo_exists())

    def test_import_dialog_modes_selection_refresh_and_worker_does_not_block_tk(self):
        source=self.root/'edited.xlsx'
        write_table(source,[['Код','Категория','name','value'],['ItPo_Test','potions','"Imported"','6'],
                            ['ItPo_New','potions','"New"','2']])
        self.app.show_spreadsheet('import')
        window=self.app.spreadsheet_window
        self.assertEqual([name for name,_ in window.mode_field.options],['С заменой','Только недостающее','Обновление'])
        window.path.set(str(source))
        original_import=__import__('gothic_editor.core.item_spreadsheet',fromlist=['ItemSpreadsheetService']).ItemSpreadsheetService.import_file
        def delayed(service,*args,**kwargs):
            sleep(.12)
            return original_import(service,*args,**kwargs)
        heartbeat=[]
        with patch('gothic_editor.ui.windows.spreadsheet.ItemSpreadsheetService.import_file',new=delayed):
            window.start()
            window.after(10,lambda:heartbeat.append(window.runner.running))
            window.close()
            self.assertTrue(window.winfo_exists())
            self.finish(window)
        self.assertEqual(heartbeat,[True])
        self.assertEqual(self.app.current.instance,'ItPo_Test')
        self.assertEqual(self.app.properties.inputs['name'].get(),'Imported')
        self.assertEqual(len(self.app.repo.project_items),2)
        self.assertIn('Создано: 1. Обновлено: 1',window.status.cget('text'))
        window.close()

    def test_invalid_import_keeps_modal_open_and_allows_retry(self):
        source=self.root/'invalid.xlsx'
        write_table(source,[['Код','name'],['ItPo_Test','plain text without quotes']])
        self.app.show_spreadsheet('import')
        window=self.app.spreadsheet_window
        window.path.set(str(source))
        window.start()
        self.finish(window)
        self.assertTrue(window.winfo_exists())
        self.assertIn('выражение Daedalus',window.status.cget('text'))
        self.assertEqual(window.start_button.cget('state'),'normal')
        self.assertEqual(self.app.current.fields['name'],'"Before"')
        window.close()
