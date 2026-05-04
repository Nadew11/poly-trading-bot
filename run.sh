#!/bin/bash
# Wrapper that sets the correct libexpat path before running the bot.
# Homebrew Python links against a newer expat than macOS ships, so we
# point DYLD_LIBRARY_PATH at the Homebrew one.
export DYLD_LIBRARY_PATH="/opt/homebrew/Cellar/expat/2.8.0/lib"
VENV_PYTHON="$(dirname "$0")/venv/bin/python3"
exec "$VENV_PYTHON" "$@"
