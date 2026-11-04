"""Collapsible hierarchy with category '+' buttons and item interactions."""
from __future__ import annotations
import tkinter as tk
from ..core.localization import tr
from .widgets import BG,PANEL,INPUT,TXT,MUTED,ACCENT,BORDER,label,make_entry
from ..core.categories import CATEGORIES,classify

class HierarchyPanel(tk.Frame):
    def __init__(self,parent,on_select,on_create,on_duplicate,on_delete,on_rename):
        super().__init__(parent,bg=PANEL)
        self.on_select=on_select;self.on_create=on_create
        self.on_duplicate=on_duplicate;self.on_delete=on_delete;self.on_rename=on_rename
        self.items=[];self.selected=None
        self.expanded={'potions':True,'weapons':True,'swords':True,'onehand':True}
        self.search=tk.StringVar()
        top=tk.Frame(self,bg=PANEL);top.pack(fill='x',padx=12,pady=(12,8))
        label(top,tr('hierarchy.title'),font=('Arial',10,'bold')).pack(side='left')
        label(top,tr('hierarchy.items'),fg=MUTED,font=('Arial',9)).pack(side='right')
        search=make_entry(self,textvariable=self.search)
        search.pack(fill='x',padx=10,pady=(0,10),ipady=6)
        search.insert(0,'')
        self.search.trace_add('write',lambda *_:self.rebuild())
        self.canvas=tk.Canvas(self,bg=PANEL,highlightthickness=0)
        scroll=tk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        scroll.pack(side='right',fill='y')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.config(yscrollcommand=scroll.set)
        self.inner=tk.Frame(self.canvas,bg=PANEL)
        self.window=self.canvas.create_window((0,0),window=self.inner,anchor='nw')
        self.inner.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width))
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.inner.bind('<MouseWheel>',self.wheel)
        self.rebuild()

    def wheel(self,event):
        self.canvas.yview_scroll(-int(event.delta/120) if event.delta else 0,'units')

    def set_items(self,items):
        self.items=items;self.rebuild()

    def choose(self,item):
        self.selected=item.instance if item else None
        self.rebuild()

    def toggle(self,key):
        self.expanded[key]=not self.expanded.get(key,False)
        self.rebuild()

    def rebuild(self):
        if not hasattr(self,'inner'):return
        pos=self.canvas.yview()
        for child in self.inner.winfo_children():child.destroy()
        query=self.search.get().strip().casefold()
        grouped={}
        for item in self.items:
            if query and query not in item.instance.casefold() and query not in item.title.casefold():continue
            grouped.setdefault(classify(item),[]).append(item)

        def row_category(cat,level):
            descendants=set()
            def collect(node):
                descendants.add(node.key)
                for child in node.children:collect(child)
            collect(cat)
            count=sum(len(grouped.get(k,[])) for k in descendants)
            row=tk.Frame(self.inner,bg=PANEL,height=32)
            row.pack(fill='x',padx=(5,5),pady=1)
            row.pack_propagate(False)
            pad=tk.Frame(row,bg=PANEL,width=level*13);pad.pack(side='left');pad.pack_propagate(False)
            open_now=self.expanded.get(cat.key,False) or bool(query)
            chevron='⌄' if open_now else '›'
            toggle=tk.Label(row,text=chevron,font=('Arial',15),fg=MUTED,bg=PANEL,width=2,cursor='hand2')
            toggle.pack(side='left');toggle.bind('<Button-1>',lambda _,k=cat.key:self.toggle(k))
            ico=label(row,cat.icon,fg=ACCENT,font=('Segoe UI Symbol',13));ico.pack(side='left',padx=(0,5))
            name=label(row,tr('categories.'+cat.key),font=('Arial',10,'bold'),anchor='w');name.pack(side='left',fill='x',expand=True)
            name.bind('<Button-1>',lambda _,k=cat.key:self.toggle(k))
            plus=tk.Label(row,text='+',bg=INPUT,fg=ACCENT,font=('Arial',14,'bold'),width=2,cursor='hand2')
            plus.pack(side='right',padx=5)
            plus.bind('<Button-1>',lambda _,k=cat.key:self.on_create(k))
            if not open_now:return
            if cat.children:
                for sub in cat.children:row_category(sub,level+1)
            for item in grouped.get(cat.key,[]):row_item(item,level+1)

        def row_item(item,level):
            selected=self.selected==item.instance
            color='#3a4d66' if selected else PANEL
            row=tk.Frame(self.inner,bg=color,height=31,cursor='hand2')
            row.pack(fill='x',padx=5,pady=1);row.pack_propagate(False)
            label(row,'',bg=color,width=level*2).pack(side='left')
            badge=label(row,'◆' if item.origin=='project' else '◇',bg=color,fg='#7bd5a9' if item.origin=='project' else MUTED,font=('Arial',10))
            badge.pack(side='left',padx=(0,6))
            title=label(row,item.title,bg=color,font=('Arial',10),anchor='w')
            title.pack(side='left',fill='x',expand=True)
            for widget in (row,badge,title):
                widget.bind('<Button-1>',lambda _,x=item:self.select(x))
                widget.bind('<Double-Button-1>',lambda _,x=item,r=row,t=title:self.rename(x,r,t))
                widget.bind('<Button-3>',lambda e,x=item:self.context(e,x))

        for cat in CATEGORIES:row_category(cat,0)
        self.canvas.update_idletasks()
        if pos:self.canvas.yview_moveto(pos[0])

    def select(self,item):
        self.selected=item.instance
        self.on_select(item)
        self.rebuild()

    def rename(self,item,row,title):
        title.pack_forget()
        text=make_entry(row,font=('Arial',10))
        text.insert(0,item.title)
        text.pack(side='left',fill='x',expand=True)
        text.focus_set();text.select_range(0,'end')
        done=[False]
        def commit(_=None):
            if done[0]:return
            done[0]=True
            value=text.get().strip()
            if value and value!=item.title:self.on_rename(item,value)
            else:self.rebuild()
        def cancel(_=None):
            done[0]=True;self.rebuild()
        text.bind('<Return>',commit);text.bind('<Escape>',cancel)

    def context(self,event,item):
        menu=tk.Menu(self,tearoff=False,bg=INPUT,fg=TXT)
        if item.origin=='project':
            menu.add_command(label=tr('hierarchy.duplicate'),command=lambda:self.on_duplicate(item))
            menu.add_command(label=tr('hierarchy.delete'),command=lambda:self.on_delete(item))
        else:
            menu.add_command(label=tr('hierarchy.duplicate_to_project'),command=lambda:self.on_duplicate(item))
            menu.add_command(label=tr('hierarchy.delete_disabled'),state='disabled')
        menu.tk_popup(event.x_root,event.y_root)
