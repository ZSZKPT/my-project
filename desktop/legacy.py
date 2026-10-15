import json
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.core import discover, upload_imgbb, RetryableUploadError
from import_tools.miaoshou import export, parse_price
from desktop.profiles import load as load_template, storage_dir, products_to_rows
from desktop.template_editor import open_editor
from desktop.print_names import read_names, title_for
from desktop.thumbnails import add_thumbnail
from desktop.tasks import Task, remember, last_task
from import_tools.image_rules import validate_groups


ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'


class App:
    def __init__(self, window):
        self.window=window
        window.title('飞凡上架 · 图片自动处理')
        window.geometry('1100x900')
        self.stop_retry=threading.Event()
        self.events=queue.Queue(); self.groups=[]; self.names=[]; self.busy=False; self.thumbnails={}
        self.variables={k:tk.StringVar(value=v) for k,v in {
            'source':'','output':'','profile':str(ASSETS/'运动短袖套装.json'),'template':str(ASSETS/'妙手Temu服饰模板.xlsx'),'price':'',
            'title':'女士圆领短袖2件套{print_name}印花圆领T恤+短裤',
            'mode':'ImgBB 自动上传','key':'','links':'','size':'1000'}.items()}
        self.active_profile=load_template(ASSETS/'运动短袖套装.json')
        self.profile_paths={'运动短袖套装（内置）':ASSETS/'运动短袖套装.json'}
        self.selected_profile=tk.StringVar(value='运动短袖套装（内置）')
        from desktop.ui import build
        build(self)
        self.refresh_templates()
        self.current_output=None
        self.last_task=last_task()
        if self.last_task is not None:
            self.resume_button.configure(state='normal')
            try:
                task=Task(self.last_task)
                if task.state['status']!='complete':
                    self.status_text.set('检测到未完成任务 · 可继续')
                    self.run_button.configure(text='继续上次中断的任务',command=self.resume_saved)
                    self.write('检测到上次任务：'+str(self.last_task))
            except (OSError,ValueError,KeyError):pass
        window.after(100,self.poll)

    def refresh_templates(self):
        directory=storage_dir()
        if directory.exists():
            for path in sorted(directory.glob('*.json')):
                try:
                    profile=load_template(path)
                    self.profile_paths[profile['name']+' · '+path.stem[-8:]]=path
                except (ValueError, OSError):continue
        self.profile_select.configure(values=list(self.profile_paths))

    def select_template(self,event=None):
        if self.busy:return
        try:
            path=self.profile_paths[self.selected_profile.get()]
            self.active_profile=load_template(path)
            self.variables['profile'].set(str(path));self.variables['title'].set(self.active_profile['title'])
            self.write('已选择模板：'+self.active_profile['name'])
        except Exception as error:messagebox.showerror('模板加载失败',str(error))

    def edit_template(self):
        if self.busy:return
        config=json.loads(json.dumps(self.active_profile));config['title']=self.variables['title'].get()
        open_editor(self.window,config,storage_dir(),self.template_saved)

    def template_saved(self,path,profile):
        self.refresh_templates()
        key=profile['name']+' · '+path.stem[-8:]
        self.profile_paths[key]=path;self.profile_select.configure(values=list(self.profile_paths));self.selected_profile.set(key)
        self.select_template()

    def import_template(self):
        if self.busy:return
        try:
            path=filedialog.askopenfilename(filetypes=[('模板JSON','*.json')])
            if not path:return
            profile=load_template(path)
            from desktop.profiles import save
            saved=save(storage_dir(),profile);self.template_saved(saved,profile)
        except Exception as error:messagebox.showerror('模板导入失败',str(error))

    def csv_tool(self):
        from desktop.main import App as CsvApp
        CsvApp(tk.Toplevel(self.window))

    def choose(self,key,folder):
        if self.busy:return
        path=filedialog.askdirectory() if folder else filedialog.askopenfilename(filetypes=[('表格','*.xlsx *.csv')])
        if path:self.variables[key].set(path)

    def scan(self):
        if self.busy:return
        try:
            old={g['sku']:v.get() for g,v in zip(self.groups,self.names)}
            self.groups=discover(self.variables['source'].get());self.scanned_source=Path(self.variables['source'].get()).resolve();self.names=[]
            for child in self.table.winfo_children():child.destroy()
            self.thumbnails={}
            self.table.columnconfigure(1,weight=1);self.table.columnconfigure(2,weight=1)
            for i,g in enumerate(self.groups):
                add_thumbnail(self,g,i)
                ttk.Label(self.table,text=f'{g["sku"]}\n{len(g["files"])} 张图片'+(' · 不足5张' if len(g['files'])<5 else ' · 超过10张' if len(g['files'])>10 else ''),style='Card.TLabel' if 5<=len(g['files'])<=10 else 'Warning.TLabel',width=20,wraplength=180).grid(row=i,column=1,sticky='w',padx=(0,8))
                variable=tk.StringVar(value=old.get(g['sku'],''));self.names.append(variable)
                ttk.Entry(self.table,textvariable=variable,width=20).grid(row=i,column=2,pady=8,padx=(0,8),sticky='ew')
            self.counts_text.set(f'{len(self.groups)} 个货号 · {sum(len(g["files"]) for g in self.groups)} 张图片')
            self.status_text.set('待填写印花名称')
            self.write('扫描完成，请逐行填写印花名称。')
        except Exception as error:messagebox.showerror('扫描失败',str(error))

    def import_names(self):
        if self.busy:return
        try:
            if not self.groups:raise ValueError('请先扫描货号')
            path=filedialog.askopenfilename(filetypes=[('印花表格','*.xlsx *.csv')])
            if not path:return
            mapping=read_names(path);matched=0
            for group,var in zip(self.groups,self.names):
                if group['sku'] in mapping:var.set(mapping[group['sku']]);matched+=1
            self.write(f'已匹配 {matched}/{len(self.groups)} 个货号，未匹配项保持原值。')
        except Exception as error:messagebox.showerror('导入失败',str(error))

    def write(self,text):
        self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')

    def start(self):
        if self.busy:return
        try:
            values={k:v.get().strip() for k,v in self.variables.items()}
            if not self.groups or any(not v.get().strip() for v in self.names):raise ValueError('先扫描并填写所有印花名称')
            if Path(values['source']).resolve()!=self.scanned_source:raise ValueError('图片目录已变化，请重新扫描')
            price=parse_price(values['price'])
            if not values['output']:raise ValueError('请选择输出目录')
            if Path(values['output']).resolve().is_relative_to(self.scanned_source):raise ValueError('输出目录必须在图片输入目录之外，避免重复扫描生成图片')
            config=json.loads(json.dumps(self.active_profile));config['title']=values['title']
            if '{print_name}' not in config['title']:raise ValueError('标题规则必须包含 {print_name}')
            titles=[title_for(config['title'],v.get().strip(),g['sku']) for g,v in zip(self.groups,self.names)]
            config['price']=price
            from desktop.profiles import validate
            validate(config)
            validate_groups(self.groups)
            if not Path(values['template']).is_file():raise ValueError('请选择官方创建商品导入模板')
            if values['mode']=='ImgBB 自动上传':
                if not values['key']:raise ValueError('请输入 ImgBB API Key')
                if not messagebox.askyesno('确认上传','将本次所有商品图和素材图上传到 ImgBB，生成公开链接。是否继续？'):return
            groups=[dict(g,print_name=v.get().strip()) for g,v in zip(self.groups,self.names)]
            self.busy=True;self.run_button.configure(state='disabled');self.scan_button.configure(state='disabled')
            self.profile_select.configure(state='disabled')
            self.resume_button.configure(state='disabled');self.load_task_button.configure(state='disabled')
            self.progress_value.set(0);self.status_text.set('正在处理');self.status_label.configure(bg='#244b53',fg='#d9eff0')
            threading.Thread(target=self.work,args=(values,config,groups),daemon=True).start()
        except Exception as error:
            messagebox.showerror('信息不完整',str(error))
            if '统一申报价' in str(error) and hasattr(self,'price_entry'):
                self.price_entry.focus_set();self.price_entry.selection_range(0,'end')

    def adopt_old_output(self):
        if self.busy:return
        try:
            if not self.groups or any(not var.get().strip() for var in self.names):raise ValueError('先扫描原始图片目录并填写/导入印花名，再接续旧版输出')
            values={key:var.get().strip() for key,var in self.variables.items()}
            config=json.loads(json.dumps(self.active_profile));config['title']=values['title'];config['price']=parse_price(values['price'])
            from desktop.profiles import validate
            validate(config)
            directory=filedialog.askdirectory(title='选择旧版失败任务的输出目录（包含图片链接.csv）')
            if not directory:return
            if not messagebox.askyesno('接续旧版输出', '请先关闭旧版软件。将沿用该目录已保存的链接和图片，并使用当前模板与申报价。旧版没有保存链接的部分仍需重新上传。是否继续？'):return
            groups=[dict(group,print_name=var.get().strip()) for group,var in zip(self.groups,self.names)]
            task=Task.adopt_legacy(directory,values,config,groups)
            self.last_task=task.path;remember(task.path);self.resume_button.configure(state='normal')
            self.write('旧版记录已接续。已保存的在线链接会复用；没有落盘的链接无法恢复。')
            self.resume_saved()
        except Exception as error:messagebox.showerror('无法接续旧输出',str(error))

    def work(self,values,config,groups,task_path=None):
        self.stop_retry.clear()
        try:
            emit=lambda kind,value:self.events.put((kind,value))
            task=Task(task_path,emit) if task_path else Task.create(values,config,groups,emit)
            while True:
                try:
                    task.run(lambda path:upload_imgbb(path,values['key']),values.get('links') or None)
                    break
                except RetryableUploadError:
                    self.events.put(('log','网络或图片服务暂时中断，3 秒后从保存的位置继续。'))
                    for remaining in (3,2,1):
                        self.events.put(('status',f'{remaining} 秒后自动继续 · 已保存进度'))
                        if self.stop_retry.wait(1):
                            raise ValueError('已停止自动重试，可手动继续上次任务') from None
        except Exception as error:
            self.events.put(('status','被动中断 · 可继续上次任务'))
            self.events.put(('log',f'任务中断：{error}。已保存的图片和链接会在继续时复用。'))
        finally:self.events.put(('done',None))

    def new_task(self):
        if self.busy:return
        self.run_button.configure(text='开始新任务并生成妙手表格',command=self.start)
        self.progress_value.set(0);self.status_text.set('准备新任务')
        self.write('已切换为新任务模式；旧任务记录仍保留，可加载继续。')

    def relocate_sources(self):
        if self.busy:return
        try:
            path=getattr(self,'last_task',None)
            if not path or not Path(path).is_file():
                selected=filedialog.askopenfilename(title='先选择任务进度.json',filetypes=[('任务记录','*.json')])
                if not selected:return
                path=Path(selected)
            directory=filedialog.askdirectory(title='选择原图现在的父目录（包含各货号文件夹）')
            if not directory:return
            count=Task(path).relink_sources(directory)
            self.last_task=Path(path);remember(path);self.resume_button.configure(state='normal')
            self.variables['source'].set(directory)
            self.write(f'已重新定位{count}个未处理货号的原图路径；原图、已处理图片及上传链接未改动。点击继续上次任务。')
            self.status_text.set('原图路径已更新 · 可继续')
        except Exception as error:messagebox.showerror('重新定位失败',str(error))

    def resume_saved(self,select=False):
        if self.busy:return
        try:
            path=getattr(self,'last_task',None)
            if select or not path or not Path(path).is_file():
                selected=filedialog.askopenfilename(title='选择之前输出目录中的任务进度.json',initialdir=self.current_output or None,filetypes=[('任务记录','*.json')])
                if not selected:return
                path=Path(selected)
            task=Task(path);settings=task.state['settings'];config=task.state['config']
            if task.needs_upload() and not self.variables['key'].get().strip():raise ValueError('请先填写本次使用的ImgBB API Key，再点击继续；密钥不会保存在任务中')
            self.last_task=Path(path)
            # Use the original immutable task snapshot rather than newly edited controls.
            self.active_profile=json.loads(json.dumps(config))
            key=config['name']+'（任务快照）';self.profile_paths[key]=task.root/task.state.get('config_file','模板配置.json')
            self.profile_select.configure(values=list(self.profile_paths));self.selected_profile.set(key)
            self.variables['title'].set(config['title']);self.variables['price'].set(str(config['price']))
            self.variables['size'].set(str(settings['size']));self.variables['mode'].set(settings['mode'])
            self.variables['output'].set(str(task.root.parent));self.variables['template'].set(str(task.root/'导入模板.xlsx'))
            links=self.variables['links'].get().strip()
            if settings['mode']!='ImgBB 自动上传' and not links:links=str(task.root/'图片链接.csv')
            values={'key':self.variables['key'].get().strip(),'links':links}
            self.busy=True;self.run_button.configure(state='disabled');self.scan_button.configure(state='disabled');self.profile_select.configure(state='disabled')
            self.resume_button.configure(state='disabled');self.load_task_button.configure(state='disabled')
            self.status_text.set('正在从保存位置继续')
            self.write('继续任务：'+str(path)+'；沿用该任务模板、价格和输出目录。')
            threading.Thread(target=self.work,args=(values,None,None,path),daemon=True).start()
        except Exception as error:messagebox.showerror('无法继续任务',str(error))

    def open_output(self):
        if not self.current_output:return
        import os,subprocess
        try:
            if sys.platform=='win32':os.startfile(self.current_output)
            elif sys.platform=='darwin':subprocess.Popen(['open',self.current_output])
            else:subprocess.Popen(['xdg-open',self.current_output])
        except OSError as error:messagebox.showerror('无法打开目录',str(error))

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='log':self.write(value)
                elif kind=='progress':self.progress_value.set(value)
                elif kind=='status':
                    self.status_text.set(value)
                    if '被动中断' in value or '待补链接' in value:self.run_button.configure(text='继续上次中断的任务',command=self.resume_saved)
                    elif '表格已生成' in value:self.run_button.configure(text='打开已生成表格所在目录',command=self.open_output)
                    self.status_label.configure(bg='#863a39' if ('失败' in value or '中断' in value) else '#176459',fg='white')
                elif kind=='task':
                    self.last_task=Path(value)
                    try:remember(self.last_task)
                    except OSError:self.write('无法保存最近任务位置；可手动加载输出目录中的任务进度.json。')
                elif kind=='output':self.current_output=value;self.open_button.configure(state='normal')
                elif kind=='done':
                    self.busy=False;self.run_button.configure(state='normal');self.scan_button.configure(state='normal');self.profile_select.configure(state='readonly')
                    self.resume_button.configure(state='normal' if getattr(self,'last_task',None) else 'disabled');self.load_task_button.configure(state='normal')
        except queue.Empty:pass
        self.window.after(100,self.poll)

if __name__=='__main__':
    window=tk.Tk();App(window);window.mainloop()
