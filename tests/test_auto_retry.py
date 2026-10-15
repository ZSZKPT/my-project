import queue
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from pathlib import Path
from tempfile import TemporaryDirectory
from desktop.core import RetryableUploadError, upload_imgbb
from desktop.legacy import App


class AutoRetryTests(unittest.TestCase):
    def worker(self, failures):
        app=App.__new__(App)
        app.events=queue.Queue()
        app.stop_retry=Mock()
        app.stop_retry.wait.return_value=False
        task=Mock()
        task.run.side_effect=failures
        return app,task

    def test_resume_same_task_after_three_seconds(self):
        app,task=self.worker([RetryableUploadError(),None])
        with patch('desktop.legacy.Task.create',return_value=task) as create:
            app.work({'key':'unused'}, {}, [])
        create.assert_called_once()
        self.assertEqual(task.run.call_count,2)
        self.assertEqual(app.stop_retry.wait.call_count,3)
        self.assertTrue(all(call.args==(1,) for call in app.stop_retry.wait.call_args_list))

    def test_permanent_failure_and_stop_do_not_retry(self):
        for error,stop in [(ValueError('missing file'),False),(RetryableUploadError(),True)]:
            app,task=self.worker([error])
            app.stop_retry.wait.return_value=stop
            with patch('desktop.legacy.Task.create',return_value=task):
                app.work({'key':'unused'}, {}, [])
            self.assertEqual(task.run.call_count,1)
            self.assertEqual(list(app.events.queue)[-1],('done',None))

    def test_upload_classifies_temporary_errors(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'image.jpg';path.write_bytes(b'image')
            for error,expected in [(HTTPError('url',503,'unavailable',{},None),RetryableUploadError),
                                   (URLError('offline'),RetryableUploadError),
                                   (HTTPError('url',403,'denied',{},None),ValueError)]:
                with patch('desktop.core.urlopen',side_effect=error):
                    with self.assertRaises(expected) as caught:upload_imgbb(path,'private-key')
                self.assertNotIn('private-key',str(caught.exception))
                if expected is ValueError:self.assertNotIsInstance(caught.exception,RetryableUploadError)
