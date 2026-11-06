"""Tiny helper that runs on the HOST and opens the native folder dialog (zenity / kdialog).
A web app in the browser or in Docker is not allowed to open the system file dialog itself,
so the API asks this helper. Protected by a random token; started and stopped by start.sh / stop.sh."""
import json
import os
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = os.environ.get("AVIA_PICKER_TOKEN", "")
PORT = int(os.environ.get("AVIA_PICKER_PORT", "8765"))


def pick(start: str) -> dict:
    start = os.path.expanduser(start or "~")
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", "--title=Aviametrics – Ordner wählen / choose folder",
               f"--filename={start.rstrip('/')}/"]
    elif shutil.which("kdialog"):
        cmd = ["kdialog", "--getexistingdirectory", start, "--title", "Aviametrics"]
    else:
        return {"error": "no dialog tool found – install zenity (sudo pacman -S zenity)"}
    r = subprocess.run(cmd, capture_output=True, text=True)
    path = r.stdout.strip()
    return {"path": path} if r.returncode == 0 and path else {"cancelled": True}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        if q.get("token", [""])[0] != TOKEN or not TOKEN:
            self.send_response(403); self.end_headers(); return
        body = json.dumps(pick(q.get("start", ["~"])[0]) if self.path.startswith("/pick") else {"ok": True}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    ThreadingHTTPServer((host, PORT), H).serve_forever()
