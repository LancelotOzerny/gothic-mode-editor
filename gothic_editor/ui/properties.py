"""Editable property form with explicit save (never changes source automatically)."""
import tkinter as tk
from .widgets import PANEL,TXT,MUTED,ACCENT,label,make_entry

class PropertiesPanel(tk.Frame):
    def __init__(self,parent,on_save):
        super().__init__(parent,bg=PANEL)
        self.on_save=on_save;self.current=None;self.inputs={}
        label(self,'СВОЙСТВА',font=('Arial',10,'bold')).pack(fill='x',padx=14,pady=(14,8))
        self.info=label(self,'Выберите предмет',fg=MUTED,anchor='w',wraplength=280,justify='left')
        self.info.pack(fill='x',padx=14,pady=(0,10))
        self.canvas=tk.Canvas(self,bg=PANEL,highlightthickness=0)
        scroll=tk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        scroll.pack(side='right',fill='y')
        self.canvas.pack(side='top',fill='both',expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.inner=tk.Frame(self.canvas,bg=PANEL)
        self.window=self.canvas.create_window((0,0),window=self.inner,anchor='nw')
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width))
        self.inner.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        self.save_btn=tk.Button(self,text='Сохранить в проект',bg='#4b79a9',fg='white',activebackground='#5888bb',relief='flat',cursor='hand2',command=self.save)
        self.save_btn.pack(fill='x',padx=12,pady=12,ipady=6)
        self.show(None)

    def show(self,item):
        self.current=item
        for child in self.inner.winfo_children():child.destroy()
        self.inputs={}
        if item is None:
            self.info.config(text='Выберите предмет в иерархии')
            self.save_btn.config(state='disabled')
            return
        self.save_btn.config(state='normal')
        self.info.config(text=f'{item.instance}\n'+('● Проект' if item.origin=='project' else '◇ Gothic II (только чтение)'))
        preferred=['name','description','visual','mainflag','flags','value','material','damageTotal','damagetype','range','on_state[0]','scemename']
        keys=[k for k in preferred if k in item.fields]
        keys+=sorted(k for k in item.fields if k not in keys)
        if 'name' not in keys:keys.insert(0,'name')
        for key in keys:
            label(self.inner,key,fg=MUTED,anchor='w',font=('Arial',9)).pack(fill='x',padx=13,pady=(6,2))
            e=make_entry(self.inner)
            e.insert(0,item.fields.get(key,'"'+item.title+'"' if key=='name' else ''))
            e.pack(fill='x',padx=13,ipady=5)
            self.inputs[key]=e
        label(self.inner,'Значения задаются как выражения Daedalus.\nСтроки вводите в кавычках.\nИзменения сохраняются только в проект.',fg=MUTED,wraplength=260,justify='left').pack(padx=12,pady=15)
        self.canvas.yview_moveto(0)

    def save(self):
        if not self.current:return
        values={k:e.get().strip() for k,e in self.inputs.items() if e.get().strip()!=self.current.fields.get(k,'') and (k in self.current.fields or e.get().strip())}
        if values:self.on_save(self.current,values)
