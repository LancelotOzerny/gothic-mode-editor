"""Modal XLSX import/export form; persistence stays in the project service."""
from pathlib import Path
from time import monotonic
import tkinter as tk
from tkinter import filedialog
from .dialog import EditorDialog
from gothic_editor.core.item_spreadsheet import MODES,ItemSpreadsheetService,export_items
from gothic_editor.ui.controllers.spreadsheet_task import SpreadsheetTask
from gothic_editor.ui.widgets.panel import Panel
from gothic_editor.ui.widgets.theme import BG,MUTED,ERROR,label
from gothic_editor.ui.widgets.progress import ProgressBar


class SpreadsheetWindow(EditorDialog):
    def __init__(self,owner,repo,operation,on_imported):
        super().__init__(owner)
        self.repo,self.operation,self.on_imported=repo,operation,on_imported
        self.title('Импорт XLSX' if operation=='import' else 'Экспорт XLSX')
        self.geometry('580x460')
        self.minsize(480,440)
        self.resizable(True,False)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.runner=SpreadsheetTask(self,self.progress,self.completed)
        self.bind('<Destroy>',lambda event:self.runner.close() if event.widget is self else None,add='+')
        self.body=Panel(self,bg=BG)
        self.body.pack(fill='both',expand=True,padx=16,pady=12)
        group=self.body.add_group('Файл XLSX')
        self.path=tk.StringVar(self)
        self.path_field=group.add_field('Файл',variable=self.path)
        self.browse_button=group.add_button('Выбрать файл…',self.browse)
        self.mode_field=None
        if operation=='import':
            self.mode_field=group.add_field('Тип импорта','choice',value='replace',
                                          options=tuple((label,key) for key,label in MODES.items()))
        else:
            self.path.set(str(repo.root/(repo.name+'.xlsx')))
            label(group.body,'Экспортируются предметы текущего проекта.',fg=MUTED).pack(fill='x',padx=8,pady=5)
        self.progress_bar=ProgressBar(self.body)
        self.progress_bar.pack(fill='x',padx=8,pady=(0,8))
        self.status=label(self.body,'',fg=MUTED,wraplength=520,justify='left',bg=BG)
        self.status.pack(fill='x',padx=8)
        footer=tk.Frame(self,bg=BG)
        footer.pack(side='bottom',fill='x',padx=20,pady=(0,12))
        self.close_button=self.add_button(footer,'Закрыть',self.close)
        self.close_button.pack(side='right')
        self.start_button=self.add_button(footer,'Импортировать' if operation=='import' else 'Экспортировать',self.start)
        self.start_button.pack(side='right',padx=8)
        self.show_centered(modal=True,focus=self.path_field)

    def browse(self):
        if self.operation=='import':
            path=filedialog.askopenfilename(parent=self,title='Импорт XLSX',filetypes=[('Excel (*.xlsx)','*.xlsx')])
        else:
            path=filedialog.asksaveasfilename(parent=self,title='Экспорт XLSX',defaultextension='.xlsx',
                initialdir=self.repo.root,initialfile=Path(self.path.get()).name,filetypes=[('Excel (*.xlsx)','*.xlsx')])
        if path:self.path.set(path)

    def start(self):
        if self.runner.running:return
        raw=self.path.get().strip()
        if not raw or Path(raw).suffix.lower()!='.xlsx':
            self.status.config(text='Выберите файл .xlsx',fg=ERROR)
            return
        destination=Path(raw).expanduser()
        if self.operation=='import' and not destination.is_file():
            self.status.config(text='Файл XLSX не найден',fg=ERROR)
            return
        if self.operation=='export' and not destination.parent.is_dir():
            self.status.config(text='Папка экспорта не найдена',fg=ERROR)
            return
        mode=self.mode_field.get() if self.mode_field is not None else None
        self.path_field.config(state='disabled')
        if self.mode_field is not None:self.mode_field.config(state='disabled')
        for button in (self.browse_button,self.start_button,self.close_button):button.config(state='disabled')
        self.status.config(text='Подготовка…',fg=MUTED)
        self.progress_bar.set(0)
        self.started=monotonic()
        items=tuple(self.repo.project_items)
        operation=(lambda progress:ItemSpreadsheetService(self.repo).import_file(destination,mode,progress)) if self.operation=='import' else (
            lambda progress:export_items(items,destination,progress))
        self.runner.start(operation)

    def progress(self,current,total,message):
        fraction=current/max(1,total)
        self.progress_bar.set(min(.99,fraction))
        self.status.config(text=f'{message} — {round(fraction*100)}%',fg=MUTED)

    def completed(self,result,error):
        self.path_field.config(state='normal')
        if self.mode_field is not None:self.mode_field.config(state='readonly')
        for button in (self.browse_button,self.start_button,self.close_button):button.config(state='normal')
        if error:
            self.status.config(text=error,fg=ERROR)
            return
        self.progress_bar.set(1)
        elapsed=monotonic()-self.started
        if self.operation=='import':
            self.on_imported()
            message=f'Создано: {result.created}. Обновлено: {result.updated}. Пропущено: {result.skipped}.'
            if result.readonly:message+=f' Из них readonly: {result.readonly}.'
        else:message=f'Экспортировано предметов: {result}.'
        self.status.config(text=f'{message} Завершено за {elapsed:.1f} с.',fg=MUTED)

    def close(self):
        if not self.runner.running:self.destroy()
