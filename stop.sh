#!/usr/bin/env bash
cd "$(dirname "$0")" && docker compose down
pkill -f tools/folder_picker.py 2>/dev/null || true
