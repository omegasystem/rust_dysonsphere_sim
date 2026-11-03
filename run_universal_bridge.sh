#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python dyson_universal_openai_bridge.py "$@"
elif [ -x "../rust_localsleep-moe/.venv_rust/bin/python" ]; then
    exec "../rust_localsleep-moe/.venv_rust/bin/python" dyson_universal_openai_bridge.py "$@"
else
    exec python3 dyson_universal_openai_bridge.py "$@"
fi
