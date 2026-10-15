import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from desktop.core import discover
from desktop.profiles import load
from desktop.tasks import Task,remember,last_task,atomic_json

ASSETS=Path(__file__).resolve().parents[1]/'desktop/assets'

class TaskPathTest(unittest.TestCase):
    def task(self,root):
        source=root/'source';folder=source/'ABC';folder.mkdir(parents=True)
        for index in range(5):Image.new('RGB',(120,160),'blue').save(folder/f'{index}.jpg')
        groups=discover(source);groups[0]['print_name']='字母印花'
        config=load(ASSETS/'运动短袖套装.json');config['price']=29
        task=Task.create({'output':str(root/'output'),'source':str(source),'size':'1000','mode':'ImgBB 自动上传','links':'','template':str(ASSETS/'妙手Temu服饰模板.xlsx')},config,groups)
        return task,source

    def test_recent_index_creates_first_use_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,source=self.task(root)
            directory=root/'new-appdata'/'templates'
            with patch('desktop.tasks.storage_dir',return_value=directory):
                remember(task.path);self.assertEqual(last_task(),task.path)
                self.assertTrue((directory.parent/'last-task.json').is_file())

    def test_relocate_moved_sources_without_changing_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,source=self.task(root);moved=root/'moved';source.rename(moved)
            before={p.name:p.read_bytes() for p in (moved/'ABC').glob('*.jpg')}
            original_json=task.path.read_bytes()
            with self.assertRaises(ValueError):task.relink_sources(root/'output')
            self.assertEqual(task.path.read_bytes(),original_json)
            self.assertEqual(task.relink_sources(moved),1)
            calls=[];task.run(lambda p:calls.append(p) or 'https://example.com/'+p.name)
            self.assertEqual(len(calls),6)
            self.assertEqual(before,{p.name:p.read_bytes() for p in (moved/'ABC').glob('*.jpg')})
            self.assertTrue((task.root/'妙手导入.xlsx').is_file())

    def test_recover_prepared_sidecar_when_sources_are_gone(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,source=self.task(root);group=task.state['groups'][0]
            task.prepare_group(group)
            before={p.name:p.read_bytes() for p in (task.root/'ABC').iterdir()}
            group['prepared']=None;task.save()  # Simulate state not saved after directory move.
            for p in (source/'ABC').iterdir():p.unlink()
            calls=[];task=Task(task.path);task.run(lambda p:calls.append(p) or 'https://example.com/'+p.name)
            self.assertEqual(len(calls),6)
            self.assertEqual(before,{p.name:p.read_bytes() for p in (task.root/'ABC').iterdir()})
