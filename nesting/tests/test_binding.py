import csv
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from binding import match_files,copy_plan,style_code
from native_bridge import NativeBridge


def entries(*names):return [{'id':str(i),'name':n,'relativePath':n,'parentName':n.replace('\\','/').split('/')[-2] if '/' in n.replace('\\','/') else n.split('-包边条')[0],'size':3} for i,n in enumerate(names)]


class BindingMatchTests(unittest.TestCase):
    def test_style_example_each_original_gets_one_even_with_different_size_or_copy(self):
        requests=[{'id':'a','filename':'YQ-TJGG-44-L-1.jpg'},
                  {'id':'b','filename':'YQ-TJGG-44-M-2.jpg'},
                  {'id':'c','filename':'YQ-TJGG-44.jpg'}]
        r=match_files(requests,entries('YQ-TJGG-44-包边条.JPG'),'style-prefix')
        self.assertEqual(len(r['matches']),3);self.assertEqual(r['missing'],[]);self.assertEqual(r['ambiguous'],[])
        self.assertEqual(len({m['file']['id'] for m in r['matches']}),1)

    def test_no_partial_style_match_and_report_ambiguous_candidates(self):
        r=match_files([{'id':'44','filename':'YQ-TJGG-44-L-1.jpg'},{'id':'4','filename':'YQ-TJGG-4-L-1.jpg'}],
                      entries('YQ-TJGG-44-包边条.jpg','YQ-TJGG-44包边条.png','YQ-TJGG-4-包边条-说明.jpg'),'style-prefix')
        self.assertEqual(len(r['ambiguous']),1);self.assertEqual(len(r['missing']),1);self.assertEqual(r['matches'],[])
        r=match_files([{'id':'44','filename':'YQ-TJGG-44-L-1.jpg'}],entries('YQ-TJGG-4-包边条.jpg'))
        self.assertEqual(len(r['missing']),1)

    def test_style_folder_requires_matching_folder_and_filename(self):
        request=[{'id':'a','filename':'YQ-TJGG-44-L-1.jpg'}]
        files=[{'id':'wrong','name':'YQ-TJGG-44-包边条.jpg','relativePath':'YQ-TJGG-45/YQ-TJGG-44-包边条.jpg','parentName':'YQ-TJGG-45'},
               {'id':'right','name':'YQ-TJGG-44-包边条.jpg','relativePath':'YQ-TJGG-44/YQ-TJGG-44-包边条.jpg','parentName':'YQ-TJGG-44'}]
        reply=match_files(request,files)
        self.assertEqual(reply['matches'][0]['file']['id'],'right')
        self.assertEqual(len(match_files(request,files[:1])['missing']),1)
        wrong_name=[{**files[1],'name':'YQ-TJGG-45-包边条.jpg'}]
        self.assertEqual(len(match_files(request,wrong_name)['missing']),1)

    def test_style_quantities_override_defaults_zero_skips_missing_and_validation(self):
        requests=[{'id':'a','filename':'YQ-TJGG-44-L-1.jpg'},{'id':'b','filename':'YQ-TJGG-44-M-2.jpg'},
                  {'id':'c','filename':'YQ-TJGG-45-L-1.jpg'}]
        files=entries('YQ-TJGG-44-包边条.jpg')
        plan=copy_plan(requests,files,quantities={'YQ-TJGG-44':5,'YQ-TJGG-45':0})
        self.assertEqual(len(plan),5);self.assertEqual(len({m['outputStem'] for m in plan}),5)
        self.assertEqual(style_code('YQ-TJGG-44-L-1.jpg'),'YQ-TJGG-44')
        for value in (-1,1.5,True,1001):
            with self.assertRaises(ValueError):copy_plan(requests,files,quantities={'YQ-TJGG-44':value,'YQ-TJGG-45':0})
        with self.assertRaises(ValueError):copy_plan(requests,files,quantities={'unknown':2})
        with self.assertRaises(ValueError):copy_plan(requests,files,quantities={'YQ-TJGG-44':0,'YQ-TJGG-45':0})

    def test_explicit_exact_rule_and_copy_number_rule(self):
        names=entries('款号-L-1_包边条.png','款号-L-包边条.jpg')
        request=[{'id':'a','filename':'款号-L-1.jpg'}]
        self.assertEqual(match_files(request,names,'exact')['matches'][0]['file']['name'],'款号-L-1_包边条.png')
        self.assertEqual(match_files(request,names,'remove-copy-number')['matches'][0]['file']['name'],'款号-L-包边条.jpg')
        with self.assertRaises(ValueError):match_files(request,names,'guess')


class FolderWindow:
    def __init__(self,choices):self.choices=list(choices);self.calls=0
    def get_current_url(self):return 'http://127.0.0.1:1234/'
    def create_file_dialog(self,*args,**kwargs):
        self.calls+=1;choice=self.choices.pop(0)
        return (str(choice),) if choice is not None else None


class BindingCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        self.source=root/'source';self.source.mkdir();self.out=root/'out';self.out.mkdir()
        self.style=self.source/'YQ-TJGG-44';self.style.mkdir()
        self.file=self.style/'YQ-TJGG-44-包边条.jpg';self.file.write_bytes(b'original-strip-image-bytes')
        self.bridge=NativeBridge('http://127.0.0.1:1234');self.window=FolderWindow([self.source,self.out]);self.bridge._window=self.window
        patcher=patch.dict(sys.modules,{'webview':SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=10))})
        patcher.start();self.addCleanup(patcher.stop)
        self.requests=[{'id':'left-right-group1','filename':'YQ-TJGG-44-L-1.jpg'},
                       {'id':'left-right-group2','filename':'YQ-TJGG-44-M-2.jpg'},
                       {'id':'repeat-import','filename':'YQ-TJGG-44-L-1.jpg'}]

    def test_scan_match_and_copy_one_per_original_with_no_overwrite(self):
        selected=self.bridge.choose_binding_folder();self.assertEqual(len(selected['files']),1)
        self.assertNotIn('path',selected['files'][0])
        matched=self.bridge.match_binding_files(self.requests);self.assertEqual(len(matched['matches']),3)
        old=self.out/'keep.jpg';old.write_bytes(b'existing')
        reply=self.bridge.copy_binding_files(self.requests);self.assertTrue(reply['saved'],reply)
        folder=Path(reply['folder']);images=list(folder.glob('*.jpg'))
        self.assertEqual(len(images),3);self.assertEqual(reply['count'],3)
        self.assertEqual(len({p.name for p in images}),3)
        for image in images:self.assertEqual(image.read_bytes(),self.file.read_bytes())
        with (folder/'包边条对应清单.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f))
        self.assertEqual(len(rows),4);self.assertEqual(old.read_bytes(),b'existing')
        self.assertFalse(list(self.out.glob('.buxu-*')))

    def test_missing_or_ambiguous_blocks_output_dialog_and_copy(self):
        self.bridge.choose_binding_folder()
        reply=self.bridge.copy_binding_files([{'id':'missing','filename':'YQ-TJGG-45-L-1.jpg'}])
        self.assertIn('error',reply);self.assertEqual(self.window.calls,1);self.assertEqual(list(self.out.iterdir()),[])
        (self.style/'YQ-TJGG-44-包边条.png').write_bytes(b'other')
        self.window.choices.insert(0,self.source);self.bridge.choose_binding_folder()
        self.assertIn('error',self.bridge.copy_binding_files(self.requests))
        self.assertEqual(self.window.calls,2);self.assertEqual(list(self.out.iterdir()),[])

    def test_same_named_file_in_wrong_folder_is_not_copied(self):
        wrong=self.source/'YQ-TJGG-45';wrong.mkdir()
        (wrong/self.file.name).write_bytes(b'wrong-style-folder')
        (self.source/self.file.name).write_bytes(b'flat-file-not-from-style-folder')
        self.bridge.choose_binding_folder()
        matched=self.bridge.match_binding_files(self.requests)
        self.assertEqual(len(matched['matches']),3)
        self.assertTrue(all(m['file']['parentName']=='YQ-TJGG-44' for m in matched['matches']))
        reply=self.bridge.copy_binding_files(self.requests);self.assertTrue(reply['saved'],reply)
        for file in Path(reply['folder']).glob('*.jpg'):self.assertEqual(file.read_bytes(),self.file.read_bytes())

    def test_manual_style_quantity_controls_actual_copy_count(self):
        self.bridge.choose_binding_folder()
        reply=self.bridge.copy_binding_files(self.requests,quantities={'YQ-TJGG-44':5})
        self.assertTrue(reply['saved'],reply);self.assertEqual(reply['count'],5)
        images=list(Path(reply['folder']).glob('*.jpg'));self.assertEqual(len(images),5)
        self.assertTrue(all(f.name.startswith('YQ-TJGG-44-包边条-') for f in images))
        for f in images:self.assertEqual(f.read_bytes(),self.file.read_bytes())

    def test_cancel_output_folder_does_not_write(self):
        self.window.choices=[self.source,None];self.bridge.choose_binding_folder()
        self.assertTrue(self.bridge.copy_binding_files(self.requests)['cancelled'])
        self.assertEqual(list(self.out.iterdir()),[])

    def test_subfolders_only_when_selected_and_external_link_excluded(self):
        nested=self.source/'sub';nested.mkdir();deep=nested/'款号';deep.mkdir();(deep/'款号-包边条.jpg').write_bytes(b'nested')
        outside=self.out/'outside-包边条.jpg';outside.write_bytes(b'outside')
        try:(self.source/'outside-包边条.jpg').symlink_to(outside)
        except OSError:pass
        self.assertEqual(len(self.bridge.choose_binding_folder()['files']),1)
        self.window.choices.insert(0,self.source)
        names=[p['name'] for p in self.bridge.choose_binding_folder(True)['files']]
        self.assertIn('款号-包边条.jpg',names);self.assertNotIn('outside-包边条.jpg',names)

    def test_copy_failure_removes_partial_output_and_keeps_originals(self):
        import shutil
        self.bridge.choose_binding_folder();copy=shutil.copy2;count=[0]
        def interrupted(source,target):
            count[0]+=1
            if count[0]==2:raise OSError('simulated copy failure')
            return copy(source,target)
        with patch('native_bridge.shutil.copy2',side_effect=interrupted):reply=self.bridge.copy_binding_files(self.requests)
        self.assertIn('error',reply);self.assertEqual(list(self.out.iterdir()),[])
        self.assertEqual(self.file.read_bytes(),b'original-strip-image-bytes')

    def test_untrusted_window_cannot_select_or_copy_local_files(self):
        with patch.object(self.window,'get_current_url',return_value='https://untrusted.example/'):
            self.assertIn('error',self.bridge.choose_binding_folder())
            self.assertIn('error',self.bridge.match_binding_files(self.requests))
            self.assertIn('error',self.bridge.copy_binding_files(self.requests))
        self.assertEqual(self.window.calls,0);self.assertEqual(list(self.out.iterdir()),[])

    def test_removed_source_aborts_and_leaves_no_partial_output(self):
        self.bridge.choose_binding_folder();self.file.unlink()
        reply=self.bridge.copy_binding_files(self.requests)
        self.assertIn('error',reply);self.assertEqual(list(self.out.iterdir()),[])

if __name__=='__main__':unittest.main()
