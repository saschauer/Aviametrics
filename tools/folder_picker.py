"""Tiny helper that runs on the HOST and opens the native folder dialog.
Primary: XDG Desktop Portal (org.freedesktop.portal.FileChooser over D-Bus) – the same mechanism Firefox,
Chromium and Flatpak apps use, so your desktop shows its own file explorer (e.g. Nautilus).
Fallback: zenity / kdialog.
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


def pick_portal(start: str) -> dict:
    """Ask the desktop for a folder via the XDG Desktop Portal (needs the pure-Python D-Bus library jeepney)."""
    import secrets
    from urllib.parse import unquote, urlparse
    from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
    from jeepney.io.blocking import Proxy, open_dbus_connection
    conn = open_dbus_connection(bus="SESSION")
    try:
        token = "avia" + secrets.token_hex(6)
        sender = conn.unique_name[1:].replace(".", "_")
        req = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response", path=req)
        Proxy(message_bus, conn).AddMatch(rule)
        with conn.filter(rule) as queue:
            portal = DBusAddress("/org/freedesktop/portal/desktop", bus_name="org.freedesktop.portal.Desktop",
                                 interface="org.freedesktop.portal.FileChooser")
            opts = {"handle_token": ("s", token), "directory": ("b", True), "modal": ("b", True)}
            if os.path.isdir(start):
                opts["current_folder"] = ("ay", start.encode() + b"\0")
            conn.send_and_get_reply(new_method_call(portal, "OpenFile", "ssa{sv}",
                                                    ("", "Aviametrics – Ordner wählen / choose folder", opts)))
            code, results = conn.recv_until_filtered(queue, timeout=600).body
        if code == 0 and "uris" in results and results["uris"][1]:
            return {"path": unquote(urlparse(results["uris"][1][0]).path)}
        return {"cancelled": True}
    finally:
        conn.close()


def pick(start: str) -> dict:
    start = os.path.expanduser(start or "~")
    try:
        return pick_portal(start)
    except Exception as e:  # no portal / no jeepney → try the classic dialog tools
        portal_error = repr(e)
    else:
        portal_error = ""
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", "--title=Aviametrics – Ordner wählen / choose folder",
               f"--filename={start.rstrip('/')}/"]
    elif shutil.which("kdialog"):
        cmd = ["kdialog", "--getexistingdirectory", start, "--title", "Aviametrics"]
    else:
        return {"error": f"no folder dialog available (portal: {portal_error})"}
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
