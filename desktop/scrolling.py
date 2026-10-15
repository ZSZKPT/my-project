"""Route wheel events to the region containing the widget, without global bindings."""
import sys
import tkinter as tk


def enable_region_scrolling(window,canvases):
    remainders={canvas:0.0 for canvas in canvases}
    for canvas in canvases:canvas.configure(yscrollincrement=16)
    def route(event):
        widget=event.widget;target=None
        while isinstance(widget,tk.Misc):
            if widget in remainders:target=widget;break
            widget=getattr(widget,'master',None)
        if target is None:return
        button=getattr(event,'num',None)
        if button in (4,5):units=-3 if button==4 else 3
        else:
            delta=getattr(event,'delta',0)
            if not delta:return
            step=-float(delta) if sys.platform=='darwin' else -float(delta)/120*3
            remainders[target]+=step;units=int(remainders[target]);remainders[target]-=units
        if units:target.yview_scroll(units,'units')
        return 'break'
    for event in ('<MouseWheel>','<Button-4>','<Button-5>'):window.bind(event,route,add='+')
