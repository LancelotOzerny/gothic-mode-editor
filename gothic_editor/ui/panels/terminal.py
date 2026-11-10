import tkinter as tk
from pathlib import Path
from queue import Empty
from gothic_editor.core.powershell import PowerShellSession
from gothic_editor.ui.widgets.panel import Panel, attach_scrollbar
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import BG, PANEL, INPUT, TXT, MUTED, label, make_entry

class TerminalPanel(Panel):
    def __init__(self, parent, on_hide):
        super().__init__(parent, bg=BG)
        self.session=None
        self.project=None
        self.history=[]
        self.history_index=0
        self._poll_id=None
        self._detached=False
        header = tk.Frame(self, bg=PANEL)
        header.pack(fill='x')
        label(header, tr('terminal.title')).pack(side='left', padx=10, pady=4)
        self.add_button('×',on_hide,parent=header).pack(side='right')
        self.add_button(tr('terminal.clear'),self.clear,parent=header).pack(side='right',padx=6)
        self.stop_button=self.add_button('Остановить',self.stop,parent=header)
        self.stop_button.pack(side='right',padx=6)
        self.stop_button.config(state='disabled')
        command_line=tk.Frame(self,bg=PANEL)
        command_line.pack(side='bottom',fill='x',padx=6,pady=5)
        self.prompt=label(command_line,'PS >',fg=MUTED)
        self.prompt.pack(side='left',padx=(0,6))
        self.command=make_entry(command_line)
        self.command.pack(side='left',fill='x',expand=True)
        self.command.bind('<Return>',self.execute)
        self.command.bind('<Up>',lambda _:self.navigate_history(-1))
        self.command.bind('<Down>',lambda _:self.navigate_history(1))
        self.command.bind('<Control-c>',self.copy_or_stop)
        self.command.bind('<Control-Cyrillic_es>',self.copy_or_stop)
        self.bind('<Destroy>',self.dispose,add='+')
        self.log = tk.Text(self, bg=INPUT, fg=TXT, insertbackground=TXT, wrap='word',
                           font=('Consolas', 10), state='disabled', relief='flat',
                           height=1)
        self.scrollbar=attach_scrollbar(self,self.log)
        self.log.pack(fill='both', expand=True)
        self.log.bind('<Button-1>',lambda _:self.log.focus_set(),add='+')
        self.log.bind('<Control-KeyPress>',self._copy_shortcut)
        self.log.bind('<<Copy>>',self.copy_selection)
        self._poll_id=self.after(30,self.poll)

    def set_project(self,project):
        project=Path(project) if project else None
        if self.project==project:return
        self.stop()
        self.project=project
        self.prompt.config(text='PS >')

    def execute(self,_event=None):
        command=self.command.get().strip()
        if not command:return 'break'
        if self.session and self.session.running:return 'break'
        if self.session is None:self.session=PowerShellSession(self.project or Path.cwd())
        self.append(f'PS {self.session.cwd}> {command}')
        try:self.session.execute(command)
        except (OSError,ValueError) as exc:
            self.append(str(exc))
            self.stop()
            return 'break'
        self.history.append(command)
        self.history=self.history[-100:]
        self.history_index=len(self.history)
        self.command.delete(0,'end')
        self.stop_button.config(state='normal')
        return 'break'

    def navigate_history(self,delta):
        self.history_index=max(0,min(len(self.history),self.history_index+delta))
        self.command.delete(0,'end')
        if self.history_index<len(self.history):self.command.insert(0,self.history[self.history_index])
        return 'break'

    def copy_or_stop(self,_event=None):
        if self.command.selection_present():self.command.event_generate('<<Copy>>')
        elif self.session and self.session.running:self.stop()
        return 'break'

    def poll(self):
        self._poll_id=None
        session=self.session
        if session:
            output=[]
            for _ in range(200):
                try:kind,value=session.events.get_nowait()
                except Empty:break
                if kind=='output':output.append(value)
                elif kind=='done':
                    session.cwd=Path(value)
                    session.running=False
                    self.prompt.config(text='PS >')
                    self.stop_button.config(state='disabled')
                elif kind=='exit':
                    output.append(f'PowerShell завершён: {value}')
                    self.stop()
            if output:self.append('\n'.join(output))
        self._poll_id=self.after(30,self.poll)

    def stop(self):
        if self.session:self.session.close()
        self.session=None
        if self.stop_button.winfo_exists():self.stop_button.config(state='disabled')
        return 'break'

    def detach(self):
        self._detached=True
        return self.session,self.project,self.history,self.history_index,self.command.get()

    def adopt(self,state):
        self.session,self.project,self.history,self.history_index,draft=state
        self.command.insert(0,draft)
        if self.session and self.session.running:self.stop_button.config(state='normal')

    def dispose(self,event):
        if event.widget is not self:return
        if self._poll_id is not None:self.after_cancel(self._poll_id)
        if not self._detached:self.stop()

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
