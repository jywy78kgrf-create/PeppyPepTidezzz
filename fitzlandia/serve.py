#!/usr/bin/env python3
"""FitzLandia LAN server.  Run:  python3 serve.py   then open the printed URL on the iPad."""
import http.server, socket, socketserver, os, sys, functools

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
ROOT = os.path.dirname(os.path.abspath(__file__))

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
