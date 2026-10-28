"""Screen-bounded Tk windows and scrolling content for small/high-DPI displays."""
import tkinter as tk
from tkinter import ttk


def fit_window(window,width,height):
    sw,sh=window.winfo_screenwidth(),window.winfo_screenheight()
    width=min(width,max(400,sw-60));height=min(height,max(300,sh-100))
    window.geometry(f'{width}x{height}')
    window.minsize(min(560,width),min(340,height))


class ScrollPanel(ttk.Frame):
    def __init__(self,parent,padding=0):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,highlightthickness=0,width=300,height=240)
        vertical=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        horizontal=ttk.Scrollbar(self,orient='horizontal',command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.rowconfigure(0,weight=1);self.columnconfigure(0,weight=1)
        self.canvas.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        self.body=ttk.Frame(self.canvas,padding=padding);self.body._scroll_host=self
        self.window=self.canvas.create_window(0,0,window=self.body,anchor='nw')
        self.body.bind('<Configure>',self.resize);self.canvas.bind('<Configure>',self.resize)
        top=self.winfo_toplevel()
        if not getattr(top,'_responsive_wheel_bound',False):
            top._responsive_wheel_bound=True;top.bind('<MouseWheel>',self.wheel,add='+')
    def resize(self,event=None):
        width=max(self.canvas.winfo_width(),self.body.winfo_reqwidth())
        self.canvas.itemconfigure(self.window,width=width);self.canvas.configure(scrollregion=self.canvas.bbox('all'))
    @staticmethod
    def wheel(event):
        widget=event.widget
        if widget.winfo_class() in ['Text','Treeview','Listbox']:return
        while widget is not None:
            host=getattr(widget,'_scroll_host',None)
            if host is not None:
                units=-int(event.delta/120) or (-1 if event.delta>0 else 1)
                if event.state&1:host.canvas.xview_scroll(units,'units')
                else:host.canvas.yview_scroll(units,'units')
                return 'break'
            widget=getattr(widget,'master',None)
