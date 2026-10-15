import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from desktop.core import discover,prepare
from desktop.profiles import load
from desktop.tasks import Task,task_lock

ASSETS=Path(__file__).resolve().parents[1]/'desktop/assets'

class ResumeTest(unittest.TestCase):
    def fixtures(self,root,count=1):
        source=root/'source';source.mkdir()
        for sku in ['ABC','DEF'][:count]:
            folder=source/sku;folder.mkdir()
            for index in range(5):Image.new('RGB',(150,200),'red').save(folder/(f'{index}-前.jpg' if index==0 else f'{index}.jpg'))
        groups=discover(source)
        for group in groups:group['print_name']='字母印花'
        config=load(ASSETS/'运动短袖套装.json');config['price']=29
        values={'source':str(source),'output':str(root/'output'),'mode':'ImgBB 自动上传','size':'1000','links':'','template':str(ASSETS/'妙手Temu服饰模板.xlsx'),'key':'TEST-NOT-REAL'}
        return groups,config,values

    def test_interruption_resumes_only_remaining_and_reuses_completed_workbook(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);groups,config,values=self.fixtures(root)
            task=Task.create(values,config,groups);calls=[]
            def flaky(path):
                calls.append(path.name)
                if len(calls)==4:raise ValueError('simulated network interruption')
                return 'https://example.com/'+path.name
            with self.assertRaises(ValueError):task.run(flaky)
            saved=json.loads(task.path.read_text(encoding='utf-8'))
            self.assertEqual(saved['status'],'interrupted');self.assertEqual(len(saved['groups'][0]['urls']),3)
            self.assertNotIn('TEST-NOT-REAL',task.path.read_text(encoding='utf-8'))
            prepared={p:p.read_bytes() for p in (task.root/'ABC').iterdir()}
            for file in groups[0]['files']:file.unlink()
            resumed=Task(task.path);new_calls=[]
            def remaining(path):new_calls.append(path.name);return 'https://example.com/'+path.name
            workbook=resumed.run(remaining)
            self.assertEqual(len(new_calls),3)
            self.assertFalse(set(new_calls)&set(calls[:3]))
            self.assertEqual(prepared,{p:p.read_bytes() for p in (task.root/'ABC').iterdir()})
            self.assertEqual(len(list((root/'output').iterdir())),1)
            self.assertEqual(workbook.name,'妙手导入.xlsx');before=workbook.read_bytes();stamp=workbook.stat().st_mtime_ns
            with patch('desktop.tasks.export',side_effect=AssertionError('must not regenerate')):
                self.assertEqual(Task(task.path).run(lambda p:self.fail('must not upload')),workbook)
            self.assertEqual(workbook.read_bytes(),before);self.assertEqual(workbook.stat().st_mtime_ns,stamp)
            # Simulate a crash after the finished XLSX rename, before final status saving.
            interrupted=json.loads(task.path.read_text(encoding='utf-8'));interrupted['status']='interrupted'
            interrupted.pop('workbook',None);interrupted.pop('workbook_sha256',None)
            task.path.write_text(json.dumps(interrupted,ensure_ascii=False),encoding='utf-8')
            with patch('desktop.tasks.export',side_effect=AssertionError('must not regenerate')):
                self.assertEqual(Task(task.path).run(lambda p:self.fail('must not upload')),workbook)
            self.assertEqual(workbook.stat().st_mtime_ns,stamp)

    def test_legacy_output_reuses_saved_complete_product_links(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);groups,config,values=self.fixtures(root,2)
            old=root/'old-output';old.mkdir();ready=[prepare(group,old,1000) for group in groups]
            links=old/'图片链接.csv'
            with links.open('w',encoding='utf-8-sig',newline='') as file:
                writer=csv.DictWriter(file,fieldnames=['sku','print_name','carousel_urls','material_url','preview_url']);writer.writeheader()
                writer.writerow({'sku':'ABC','print_name':'字母印花','carousel_urls':'|'.join('https://example.com/ABC/'+p.name for p in ready[0]['carousel']),'material_url':'https://example.com/ABC/material.jpg'})
            before=links.read_bytes()
            task=Task.adopt_legacy(old,values,config,groups)
            self.assertEqual((old/'图片链接_续作前.csv').read_bytes(),before)
            calls=[]
            task.run(lambda path:calls.append(path) or 'https://example.com/DEF/'+path.name)
            self.assertEqual(len(calls),6)
            self.assertTrue(all(p.parent.name=='DEF' for p in calls))
            self.assertTrue((old/'妙手导入.xlsx').is_file())

    def test_concurrent_task_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);groups,config,values=self.fixtures(root)
            task=Task.create(values,config,groups)
            with task_lock(task.root):
                with self.assertRaises(ValueError):task.run(lambda p:self.fail('must not upload'))
