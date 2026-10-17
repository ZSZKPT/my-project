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
        root.destroy(); return
    root.mainloop()


if __name__ == '__main__': main()
