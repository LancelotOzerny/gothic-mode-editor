"""Docked operation output and a task runner independent of the dock's lifetime."""
import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk

from ..core.localization import tr
from .widgets import BG, PANEL, INPUT, TXT, label


class TerminalPanel(tk.Frame):
    def __init__(self, parent, on_hide):
        super().__init__(parent, bg=BG)
        header = tk.Frame(self, bg=PANEL)
        header.pack(fill='x')
        label(header, tr('terminal.title')).pack(side='left', padx=10, pady=4)
        ttk.Button(header, text='×', width=3, command=on_hide).pack(side='right')
        ttk.Button(header, text=tr('terminal.clear'), command=self.clear).pack(side='right', padx=6)
        scroll = ttk.Scrollbar(self)
        scroll.pack(side='right', fill='y')
        self.log = tk.Text(self, bg=INPUT, fg=TXT, insertbackground=TXT, wrap='word',
                           font=('Consolas', 10), state='disabled', relief='flat',
                           yscrollcommand=scroll.set, height=1)
        self.log.pack(fill='both', expand=True)
        scroll.config(command=self.log.yview)
        self.log.bind('<Button-1>',lambda _:self.log.focus_set(),add='+')
        self.log.bind('<Control-KeyPress>',self._copy_shortcut)
        self.log.bind('<<Copy>>',self.copy_selection)

    def _copy_shortcut(self,event):
        if (event.keysym.lower() in ('c','cyrillic_es') or
                (event.keycode==67 and self.tk.call('tk','windowingsystem')=='win32')):
            return self.copy_selection()

    def copy_selection(self,_event=None):
        if self.log.tag_ranges('sel'):
            text=self.log.get('sel.first','sel.last')
            self.log.clipboard_clear()
            self.log.clipboard_append(text)
        return 'break'

    def append(self, message):
        self.log.config(state='normal')
        self.log.insert('end', message + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 5000:
            self.log.delete('1.0', '1001.0')
        self.log.see('end')
        self.log.config(state='disabled')

    def clear(self):
        self.log.config(state='normal')
        self.log.delete('1.0', 'end')
        self.log.config(state='disabled')


class ToolRunner:
    def __init__(self, scheduler, append, on_complete):
        self.scheduler = scheduler
        self.append = append
        self.on_complete = on_complete
        self.running = False
        self.messages = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='project-tools')
        self.on_progress = lambda _:None

    def start(self, title, operation, log_path=None):
        if self.running:
            return
        self.running = True
        self.log_path = log_path
        self.append('\n' + title)
        self.future = self.executor.submit(operation, self.messages.put)
        self.scheduler.after(50, self.poll)

    def poll(self):
        while True:
            try:
                message=self.messages.get_nowait()
                self.append(message)
                self.on_progress(message)
            except queue.Empty:
                break
        if not self.future.done():
            self.scheduler.after(50, self.poll)
            return
        success, result, error = False, None, None
        try:
            result = self.future.result()
            success = True
        except Exception as exc:
            error = str(exc)
        if self.log_path is not None and self.log_path.is_file():
            try:
                with self.log_path.open('rb') as stream:
                    stream.seek(max(0, self.log_path.stat().st_size - 128 * 1024))
                    self.append(stream.read().decode('utf-8', errors='replace'))
            except OSError as exc:
                self.append(str(exc))
        if success:
            if getattr(result,'archive',None) is not None:
                self.append(tr('item_assets.archive_result',path=str(result.archive)))
            operation=getattr(result,'operation','compile' if self.log_path is not None else 'sync')
            key={'compile':'tools.compile_success','sync':'tools.sync_success','launch':'pipeline.launch_success'}[operation]
            if getattr(result,'manual',False):self.append(tr('pipeline.manual_launch',name=result.output.name))
            self.append(tr(key,path=str(result.output),count=result.files,warnings=result.warnings))
            if result.backup is not None:
                self.append(tr('tools.backup',path=str(result.backup)))
        else:
            self.append(error)
        self.running = False
        self.on_complete(success, result)

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
