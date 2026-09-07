#!/usr/bin/env python3
"""FitzLandia LAN server.  Run:  python3 serve.py   then open the printed URL on the iPad."""
import http.server, socket, socketserver, os, sys, functools

# Default is an uncommon high port so it never collides with other apps.
# If it is somehow busy, the next free port from the list is used.
PREFERRED = [47321, 47322, 47323, 47324, 47325]
ROOT = os.path.dirname(os.path.abspath(__file__))

def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False

def pick_port():
    if len(sys.argv) > 1:
        return int(sys.argv[1])
    for p in PREFERRED:
        if port_free(p):
            return p
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # let the OS choose
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]

PORT = pick_port()

def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()
    def log_message(self, fmt, *args):
        pass

socketserver.TCPServer.allow_reuse_address = True
handler = functools.partial(Handler, directory=ROOT)
with socketserver.TCPServer(("0.0.0.0", PORT), handler) as httpd:
    ip = lan_ip()
    print("=" * 56)
    print("  FitzLandia is running!")
    print(f"  On the iPad (same wifi) open Safari and go to:")
    print(f"      http://{ip}:{PORT}")
    print(f"  On this laptop:  http://localhost:{PORT}")
    print("  Tip: Share > Add to Home Screen on the iPad for full screen.")
    print("  Press Ctrl+C to stop.")
    print("=" * 56)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
