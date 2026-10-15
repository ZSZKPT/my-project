import copy
import json
import tkinter as tk
from tkinter import ttk, messagebox
from desktop.profiles import validate, save


def open_editor(parent,current,directory,on_saved):
    window=tk.Toplevel(parent);window.title('飞凡上架 · 另存为产品模板');window.geometry('900x780')
    base=copy.deepcopy(current);entries={}
    labels={'name':'模板名称','main_suffix':'主图文件名后缀（不含扩展名，可留空）','title':'中文标题规则（含 {print_name}，可加 {sku}）','english_title':'英文标题规则（可加 {sku}）','category_id':'Temu类目ID','origin':'产地','color':'颜色','description':'共用描述','packaging_shape':'外包装形状','packaging_type':'外包装类型','packaging_image':'固定包装图片链接'}
    for row,(key,label) in enumerate(labels.items()):
        ttk.Label(window,text=label).grid(row=row,column=0,sticky='w',padx=10,pady=5)
        var=tk.StringVar(value=str(base.get(key,'前' if key=='main_suffix' else '')));entries[key]=var
        ttk.Entry(window,textvariable=var,width=70).grid(row=row,column=1,sticky='ew',padx=10)
    row=len(labels)
    ttk.Label(window,text='尺码参数JSON：size、length_cm、width_cm、height_cm、weight_g，可选net_weight_g').grid(row=row,column=0,columnspan=2,sticky='w',padx=10,pady=6)
    text=tk.Text(window,height=14);text.grid(row=row+1,column=0,columnspan=2,sticky='nsew',padx=10);text.insert('1.0',json.dumps(base['variants'],ensure_ascii=False,indent=2))
    def commit():
        try:
            profile={k:v.get().strip() for k,v in entries.items()};profile['variants']=json.loads(text.get('1.0','end'))
            validate(profile);path=save(directory,profile);on_saved(path,profile);window.destroy()
        except Exception as error:messagebox.showerror('模板保存失败',str(error),parent=window)
    ttk.Button(window,text='保存新模板（不覆盖旧模板）',command=commit).grid(row=row+2,column=0,columnspan=2,pady=12)
    window.columnconfigure(1,weight=1);window.rowconfigure(row+1,weight=1)
