#!/bin/bash
cd "$(dirname "$0")"
# Prefer Anaconda Python 3.11 (required for py-clob-client); fall back to PATH.
if [ -x "$HOME/anaconda3/bin/python3.11" ]; then
  exec "$HOME/anaconda3/bin/python3.11" beast_mode_bot.py --dashboard
elif command -v python3.11 >/dev/null 2>&1; then
  exec python3.11 beast_mode_bot.py --dashboard
else
  exec python3 beast_mode_bot.py --dashboard
fi
