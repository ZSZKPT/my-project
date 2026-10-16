#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -c 'import sys; assert sys.version_info >= (3,12), "需要 Python 3.12+"'
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import shapely, PIL, svgelements' 2>/dev/null; then
  .venv/bin/python -m pip install -r requirements.lock
fi
.venv/bin/python -m pip check
echo '浏览器打开 http://127.0.0.1:8765 ，终端按 Ctrl+C 退出。'
exec .venv/bin/python server.py --port 8765
