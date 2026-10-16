"""Visible Windows startup, readiness checks, and a persistent diagnostic log."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent


def main():
    os.chdir(ROOT)
    logfile = ROOT / 'startup.log'
    with logfile.open('w', encoding='utf-8') as log:
        def say(message):
            print(message, flush=True)
            log.write(message + '\n')
            log.flush()

        def pump(process):
            for line in process.stdout:
                say(line.rstrip())

        def command(args):
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace')
            pump(process)
            if process.wait():
                raise RuntimeError('Command failed. See output above and startup.log.')

        def healthy():
            try:
                with urlopen('http://127.0.0.1:8765/api/health', timeout=0.5) as response:
                    body = json.load(response)
                    return body.get('ok') is True and body.get('app') == 'nesting'
            except (OSError, ValueError):
                return False

        try:
            say('Buxu nesting - Windows startup')
            say('Python: ' + sys.version.split()[0])
            say('Folder: ' + str(ROOT))
            if sys.version_info < (3, 12):
                raise RuntimeError('Python 3.12 or newer is required. Install from https://www.python.org/downloads/windows/')
            python = ROOT / '.venv' / 'Scripts' / 'python.exe'
            if not python.exists():
                say('[1/4] Creating local Python environment...')
                command([sys.executable, '-m', 'venv', str(ROOT / '.venv')])
            else:
                say('[1/4] Existing .venv found.')
            say('[2/4] Checking / installing dependencies. First install can take several minutes.')
            command([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(ROOT / 'requirements.lock')])
            command([str(python), '-m', 'pip', 'check'])
            say('[3/4] Starting the local application...')
            if healthy():
                say('An existing Buxu server is already running on port 8765.')
                say('Opening http://127.0.0.1:8765 in your browser.')
                webbrowser.open('http://127.0.0.1:8765')
                return 0
            process = subprocess.Popen([str(python), '-u', str(ROOT / 'server.py'), '--port', '8765'],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace')
            reader = threading.Thread(target=pump, args=(process,), daemon=True)
            reader.start()
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        reader.join(timeout=2)
                        raise RuntimeError('Server exited before startup. Check the error above; port 8765 may be in use.')
                    if healthy():
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError('Server did not become ready. Check startup.log.')
                say('[4/4] READY: http://127.0.0.1:8765')
                say('Keep this window open. Press Ctrl+C to stop the application.')
                webbrowser.open('http://127.0.0.1:8765')
                code = process.wait()
                reader.join(timeout=2)
                return code
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                reader.join(timeout=2)
        except KeyboardInterrupt:
            say('Application stopped.')
            return 0
        except Exception as exc:
            say('STARTUP FAILED: ' + str(exc))
            say('Diagnostic log: ' + str(logfile))
            say('Send a screenshot of this window, or the startup.log file, for diagnosis.')
            return 1


if __name__ == '__main__':
    sys.exit(main())
