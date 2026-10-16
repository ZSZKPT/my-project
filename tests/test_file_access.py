import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_resume as fixtures
from desktop.tasks import Task
from desktop.file_access import TaskFileAccessError,explain_file_error


class FileAccessTest(unittest.TestCase):
    def test_denied_csv_preserves_original_and_uses_one_durable_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            groups,config,values=fixtures.ResumeTest().fixtures(Path(directory))
            logs=[];task=Task.create(values,config,groups,lambda kind,value:logs.append((kind,value)))
            target=task.root/'图片链接.csv';target.write_text('人工保留内容',encoding='utf-8')
            before={p:p.read_bytes() for p in groups[0]['files']}
            replace=os.replace
            def deny_csv(source,destination):
                if Path(destination)==target:raise PermissionError(13,'denied',str(destination))
                return replace(source,destination)
            uploads=[]
            with patch('desktop.tasks.os.replace',side_effect=deny_csv):
                workbook=task.run(lambda p:uploads.append(p) or 'https://example.com/'+p.name)
            self.assertEqual(len(uploads),6)
            self.assertEqual(target.read_text(encoding='utf-8'),'人工保留内容')
            saved=json.loads(task.path.read_text(encoding='utf-8'))
            self.assertEqual(saved['status'],'complete');self.assertEqual(len(saved['groups'][0]['urls']),6)
            self.assertEqual(len(list(task.root.glob('图片链接_续作_*.csv'))),1)
            self.assertTrue(task.local(saved['links_file']).is_file());self.assertTrue(workbook.is_file())
            self.assertEqual(before,{p:p.read_bytes() for p in groups[0]['files']})
            with patch('desktop.tasks.export',side_effect=AssertionError('must reuse workbook')):
                self.assertEqual(Task(task.path).run(lambda p:self.fail('must reuse uploads')),workbook)

    def test_checkpoint_permission_error_stops_before_upload_and_keeps_saved_state(self):
        with tempfile.TemporaryDirectory() as directory:
            groups,config,values=fixtures.ResumeTest().fixtures(Path(directory))
            task=Task.create(values,config,groups);before=task.path.read_bytes();replace=os.replace
            def deny_checkpoint(source,destination):
                if Path(destination)==task.path:raise PermissionError(13,'denied',str(destination))
                return replace(source,destination)
            with patch('desktop.tasks.os.replace',side_effect=deny_checkpoint):
                with self.assertRaises(TaskFileAccessError) as caught:
                    task.run(lambda p:self.fail('must not upload without a writable checkpoint'))
            self.assertEqual(task.path.read_bytes(),before)
            self.assertIn(str(task.path),explain_file_error(caught.exception,task.path))

    def test_winerror_without_filename_explains_task_context(self):
        error=PermissionError('拒绝访问');error.winerror=5
        message=explain_file_error(error,r'C:\Tasks\任务进度.json')
        self.assertIn('WinError 5',message);self.assertIn('系统未提供具体文件名',message)
        self.assertIn(r'C:\Tasks\任务进度.json',message)

    def test_transient_windows_checkpoint_denial_retries_without_losing_state(self):
        from desktop.tasks import atomic_json
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'任务进度.json';target.write_text('old')
            replace=os.replace;calls=[]
            def transient(source,destination):
                calls.append(1)
                if len(calls)==1:
                    error=PermissionError('occupied');error.winerror=5;raise error
                return replace(source,destination)
            with patch('desktop.tasks.os.replace',side_effect=transient),patch('desktop.tasks.time.sleep') as sleep:
                atomic_json(target,{'saved':True})
            self.assertEqual(json.loads(target.read_text()),{'saved':True});sleep.assert_called_once_with(0.3)

    def test_manual_task_switches_to_auto_and_only_uploads_missing_links(self):
        with tempfile.TemporaryDirectory() as directory:
            groups,config,values=fixtures.ResumeTest().fixtures(Path(directory))
            values['mode']='手动填写链接';task=Task.create(values,config,groups)
            self.assertIsNone(task.run(lambda p:self.fail('manual mode must not upload')))
            group=task.state['groups'][0];first=group['prepared']['carousel'][0]
            group['urls'][first]='https://example.com/saved.jpg';task.save()
            self.assertEqual(task.missing_link_summary(),[('ABC',4,True)])
            snapshot=json.loads(json.dumps(task.state['config']));prepared=group['prepared'].copy()
            task.enable_auto_upload();calls=[]
            workbook=task.run(lambda p:calls.append(p) or 'https://example.com/'+p.name)
            self.assertEqual(len(calls),5);self.assertTrue(workbook.is_file())
            self.assertEqual(task.state['config'],snapshot);self.assertEqual(task.state['groups'][0]['prepared'],prepared)
            self.assertEqual(task.state['groups'][0]['urls'][first],'https://example.com/saved.jpg')
            self.assertEqual(task.missing_link_summary(),[])
            before=task.path.read_bytes();task.enable_auto_upload();self.assertEqual(before,task.path.read_bytes())

    def test_permanent_windows_denial_has_bounded_retries_and_preserves_checkpoint(self):
        from desktop.tasks import atomic_json
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'任务进度.json';target.write_text('original')
            error=PermissionError('denied');error.winerror=5
            with patch('desktop.tasks.os.replace',side_effect=error) as replace,patch('desktop.tasks.time.sleep') as sleep:
                with self.assertRaises(TaskFileAccessError):atomic_json(target,{'new':True})
            self.assertEqual(replace.call_count,4);self.assertEqual(sleep.call_count,3)
            self.assertEqual(target.read_text(),'original');self.assertEqual(list(Path(directory).glob('*.tmp')),[])
