import csv
import json
import math
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.core import discover, prepare, upload_imgbb, load_profile
from import_tools.dianxiaomi import export


ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'


class App:
    def __init__(self, window):
        self.window=window
        window.title('Temu · 店小秘批量导入工具')
        window.geometry('1000x800')
        self.events=queue.Queue(); self.groups=[]; self.names=[]; self.busy=False
        self.variables={k:tk.StringVar(value=v) for k,v in {
            'source':'','output':'','profile':str(ASSETS/'运动短袖短裤套装.xlsx'),'template':str(ASSETS/'店小秘创建商品模板.xlsx'),'price':'',
            'title':'女士圆领短袖2件套{print_name}印花圆领T恤+短裤',
            'mode':'ImgBB 自动上传','key':'','links':'','size':'1000'}.items()}
        frame=ttk.Frame(window,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='选择图片 → 填印花名和申报价 → 处理图片 / 上传 → 导出 Excel',font=('',13,'bold')).pack(anchor='w')
        self.controls=[]
        for key,label,folder in [('source','图片目录',True),('output','输出目录',True),('profile','商品模板（商品导出表）',False),('template','创建商品导入模板',False)]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=4)
            ttk.Label(row,text=label,width=26).pack(side='left')
            ttk.Entry(row,textvariable=self.variables[key]).pack(side='left',fill='x',expand=True)
            button=ttk.Button(row,text='选择',command=lambda k=key,f=folder:self.choose(k,f));button.pack(side='left');self.controls.append(button)
        for key,label in [('title','标题规则（含 {print_name}）'),('price','统一申报价（店铺币种）')]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=4);ttk.Label(row,text=label,width=26).pack(side='left');ttk.Entry(row,textvariable=self.variables[key]).pack(side='left',fill='x',expand=True)
        row=ttk.Frame(frame);row.pack(fill='x',pady=4)
        ttk.Label(row,text='素材图尺寸',width=26).pack(side='left');ttk.Combobox(row,textvariable=self.variables['size'],values=['800','1000','1200'],state='readonly',width=10).pack(side='left')
        ttk.Label(row,text='建议1000：导入模板要求大于800；居中裁切需核对构图').pack(side='left',padx=12)
        row=ttk.Frame(frame);row.pack(fill='x',pady=4)
        ttk.Label(row,text='图片上传方式',width=26).pack(side='left');ttk.Combobox(row,textvariable=self.variables['mode'],values=['先处理图片，手动补链接','ImgBB 自动上传'],state='readonly').pack(side='left')
        row=ttk.Frame(frame);row.pack(fill='x',pady=4);ttk.Label(row,text='ImgBB API Key（不保存）',width=26).pack(side='left');ttk.Entry(row,textvariable=self.variables['key'],show='*').pack(side='left',fill='x',expand=True)
        row=ttk.Frame(frame);row.pack(fill='x',pady=4);ttk.Label(row,text='已有图片链接 CSV（可选）',width=26).pack(side='left');ttk.Entry(row,textvariable=self.variables['links']).pack(side='left',fill='x',expand=True);ttk.Button(row,text='选择',command=lambda:self.choose('links',False)).pack(side='left')
        ttk.Label(frame,text='上传会将图片交给 ImgBB 并生成公开链接；密钥仅用于本次运行。手动模式不会上传。').pack(anchor='w',pady=4)
        self.scan_button=ttk.Button(frame,text='扫描货号 / 刷新名称表',command=self.scan);self.scan_button.pack(anchor='w')
        self.canvas=tk.Canvas(frame,height=150);self.canvas.pack(fill='both',expand=True,pady=6)
        self.table=ttk.Frame(self.canvas);self.canvas.create_window((0,0),window=self.table,anchor='nw')
        scrollbar=ttk.Scrollbar(frame,orient='vertical',command=self.canvas.yview);scrollbar.pack(side='right',fill='y');self.canvas.configure(yscrollcommand=scrollbar.set)
        self.table.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.run_button=ttk.Button(frame,text='开始处理 / 生成 Excel',command=self.start);self.run_button.pack(anchor='w',pady=6)
        self.log=tk.Text(frame,height=9,state='disabled');self.log.pack(fill='x')
        ttk.Label(frame,text='导入创建新商品，不复制类目属性或尺码表，也不自动发布。原文件不会覆盖。').pack(anchor='w')
        window.after(100,self.poll)

    def choose(self,key,folder):
        if self.busy:return
        path=filedialog.askdirectory() if folder else filedialog.askopenfilename(filetypes=[('表格','*.xlsx *.csv')])
        if path:self.variables[key].set(path)

    def scan(self):
        if self.busy:return
        try:
            old={g['sku']:v.get() for g,v in zip(self.groups,self.names)}
            self.groups=discover(self.variables['source'].get());self.names=[]
            for child in self.table.winfo_children():child.destroy()
            for i,g in enumerate(self.groups):
                ttk.Label(self.table,text=f'{g["sku"]}  ({len(g["files"])}张)',width=45).grid(row=i,column=0,sticky='w')
                variable=tk.StringVar(value=old.get(g['sku'],''));self.names.append(variable)
                ttk.Entry(self.table,textvariable=variable,width=35).grid(row=i,column=1,pady=2)
            self.write('扫描完成，请逐行填写印花名称。')
        except Exception as error:messagebox.showerror('扫描失败',str(error))

    def write(self,text):
        self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')

    def start(self):
        if self.busy:return
        try:
            values={k:v.get().strip() for k,v in self.variables.items()}
            if not self.groups or any(not v.get().strip() for v in self.names):raise ValueError('先扫描并填写所有印花名称')
            price=float(values['price'])
            if not math.isfinite(price) or price<=0:raise ValueError('请填写正数申报价')
            if not values['output']:raise ValueError('请选择输出目录')
            config=load_profile(values['profile']);config['title']=values['title']
            if '{print_name}' not in config['title']:raise ValueError('标题规则必须包含 {print_name}')
            titles=[config['title'].replace('{print_name}',v.get().strip()).replace('{sku}',g['sku']) for g,v in zip(self.groups,self.names)]
            if len(titles)!=len(set(titles)):raise ValueError('不同货号生成了相同标题，请使用不同印花名或增加 {sku}')
            for v in config['variants']:v['price']=price
            if not Path(values['template']).is_file():raise ValueError('请选择官方创建商品导入模板')
            if values['mode']=='ImgBB 自动上传':
                if not values['key']:raise ValueError('请输入 ImgBB API Key')
                if not messagebox.askyesno('确认上传','将本次所有商品图和素材图上传到 ImgBB，生成公开链接。是否继续？'):return
            groups=[dict(g,print_name=v.get().strip()) for g,v in zip(self.groups,self.names)]
            self.busy=True;self.run_button.configure(state='disabled');self.scan_button.configure(state='disabled')
            threading.Thread(target=self.work,args=(values,config,groups),daemon=True).start()
        except Exception as error:messagebox.showerror('信息不完整',str(error))

    def work(self,values,config,groups):
        try:
            out=Path(values['output'])/('店小秘_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True,exist_ok=False)
            self.events.put(('log',f'输出目录：{out}'))
            link_rows={}
            if values['links']:
                with open(values['links'],encoding='utf-8-sig',newline='') as f:
                    for r in csv.DictReader(f):
                        if r.get('sku') in link_rows:raise ValueError('链接表有重复货号')
                        link_rows[r['sku']]=r
            products=[]
            link_file=out/'图片链接.csv'
            with open(link_file,'w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=['sku','print_name','carousel_urls','material_url','preview_url']);writer.writeheader()
                for g in groups:
                    if len(g['files'])>10:raise ValueError(f'{g["sku"]} 超过10张，请先移除不需要的轮播图')
                    ready=prepare(g,out,int(values['size']));self.events.put(('log',f'{g["sku"]} 图片处理完成'))
                    row={'sku':g['sku'],'print_name':g['print_name'],'carousel_urls':'','material_url':'','preview_url':''}
                    if values['mode']=='ImgBB 自动上传':
                        urls=[]
                        for path in ready['carousel']:
                            urls.append(upload_imgbb(path,values['key']))
                            self.events.put(('log',f'{g["sku"]} 已上传 {len(urls)} 张'))
                        row.update(carousel_urls='|'.join(urls),material_url=upload_imgbb(ready['material'],values['key']),preview_url=urls[0])
                    elif g['sku'] in link_rows:
                        row.update({k:link_rows[g['sku']].get(k,'') for k in ['carousel_urls','material_url','preview_url']})
                    writer.writerow(row);f.flush();products.append(row)
            (out/'模板配置.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
            if all(p['carousel_urls'] and p['material_url'] for p in products):
                count=export(values['template'],config,products,out/'店小秘导入.xlsx');self.events.put(('log',f'已生成 Excel：{count} 行 SKU，需在店小秘测试导入。'))
            else:self.events.put(('log','尚缺在线链接：已生成图片和图片链接.csv。上传后填写链接表，下次选择该 CSV 再生成 Excel。'))
            self.events.put(('log','完成。请核对主图排序、素材裁切和价格；尚未发布商品。'))
        except Exception as error:self.events.put(('log',f'处理停止：{error}。已生成文件保留；已上传图片不会自动删除。'))
        finally:self.events.put(('done',None))

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='log':self.write(value)
                else:self.busy=False;self.run_button.configure(state='normal');self.scan_button.configure(state='normal')
        except queue.Empty:pass
        self.window.after(100,self.poll)

if __name__=='__main__':
    window=tk.Tk();App(window);window.mainloop()
