import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import tkinter as tk
    from print_studio.app import App
    root = tk.Tk(); app = App(root)
    if '--self-test' in sys.argv:
        import tempfile
        from print_studio.app import ASSETS
        from print_studio.jobs import Job
        from print_studio.core import settings
        root.update()
        with tempfile.TemporaryDirectory() as directory:
            options = settings({'width_cm': 10, 'height_cm': 12, 'tile_cm': 3, 'dpi': 72, 'offset_x_cm': 0, 'offset_y_cm': 0})
            job = Job.create([ASSETS / 'demo' / 'geometric.png'], directory, options, [ASSETS / 'demo' / 'template.json'])
            job.run(); app.show_image(job.root / job.state['items'][0]['id'] / '套版效果_01.png')
            app.large_preview(); root.update()
            assert app.preview_window.winfo_exists()
            app.show_image(ASSETS / 'demo' / 'geometric.png'); root.update()
            assert app.preview_window is None
            app.set_files([ASSETS / 'demo' / 'geometric.png']); root.update()
            from zipfile import ZipFile
            from io import BytesIO
            from PIL import Image, ImageDraw
            from print_studio.templates import import_zip, approve
            sample=Image.new('RGB',(500,400),'white'); draw=ImageDraw.Draw(sample)
            draw.rectangle((20,20,200,360),fill='#112040',outline='black'); draw.rectangle((260,30,460,350),fill='white',outline='black',width=2)
            stream=BytesIO(); sample.save(stream,'JPEG',dpi=(110,110))
            archive=Path(directory)/'panels.zip'
            with ZipFile(archive,'w') as z:z.writestr('TEST-S.jpg',stream.getvalue())
            paths=import_zip(archive,Path(directory)/'library','cutting'); approve(paths[0])
            app.templates=paths;app.refresh_templates();app.template_list.selection_set(0)
            app.review_template();root.update();assert app.template_window.winfo_exists();app.template_window.destroy()
            app.edit_template_mask();root.update();assert app.mask_editor.window.winfo_exists()
            from types import SimpleNamespace
            app.mask_editor.press(SimpleNamespace(x=40,y=40));app.mask_editor.release();app.mask_editor.undo();root.update();app.mask_editor.close()
            cut_job=Job.create([ASSETS/'demo'/'geometric.png'],directory,options,paths);cut_job.run()
            assert any(p.name.startswith('裁片_') for p in (cut_job.root/cut_job.state['items'][0]['id']).glob('*.png'))

        root.destroy(); return
    root.mainloop()


if __name__ == '__main__': main()
