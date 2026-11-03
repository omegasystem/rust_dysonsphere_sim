#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ -x "../rust_localsleep-moe/.venv_rust/bin/python" ]; then
    exec ../rust_localsleep-moe/.venv_rust/bin/python dyson_pyqt_gui.py "$@"
else
    exec python3 dyson_pyqt_gui.py "$@"
fi
