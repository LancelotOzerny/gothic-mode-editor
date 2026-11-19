"""Shared interface colours, geometry and painting helpers."""
import tkinter as tk

BG='#202735';PANEL='#2b3545';INPUT='#1d2532';TXT='#e8edf6';MUTED='#98a7bd';ACCENT='#80b4f9';BORDER='#3b4758'

def label(parent,text='',**kw):
    return tk.Label(parent,text=text,bg=kw.pop('bg',PANEL),fg=kw.pop('fg',TXT),**kw)

FIELD_HEIGHT = 40
COMPACT_FIELD_HEIGHT = FIELD_HEIGHT // 2
FIELD_CONTENT_PADDING = 5
# Tk grid and pack use whole pixels. Keep five pixels of total vertical padding.
COMPACT_FIELD_PADDING = (2, 3)
SAVED = '#7bd5a9'
UNSAVED = '#efc86a'
ERROR = '#ef9a9a'
FIELD_FONT = 'TkDefaultFont'
OPTION_BG = '#293444'
HOVER_BG = '#354257'

def rounded_box(canvas, width, height, fill, border=BORDER):
    """Two-pixel corners; the native entry lives inside the painted surface."""
    canvas.delete('surface')
    for inset, color in ((0, border), (1, fill)):
        x, y, right, bottom = inset, inset, width-inset, height-inset
        radius = max(1, 2-inset)
        canvas.create_polygon(x+radius,y,right-radius,y,right,y,right,y+radius,
            right,bottom-radius,right,bottom,right-radius,bottom,x+radius,bottom,
            x,bottom,x,bottom-radius,x,y+radius,x,y, smooth=True, splinesteps=12,
            fill=color, outline='', tags='surface')
    canvas.tag_lower('surface')

def blend(start, end, amount):
    a = [int(start[i:i+2], 16) for i in (1,3,5)]
    b = [int(end[i:i+2], 16) for i in (1,3,5)]
    return '#%02x%02x%02x' % tuple(round(x+(y-x)*amount) for x,y in zip(a,b))
