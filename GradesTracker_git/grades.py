from pathlib import Path
import os
import json
import time
import threading
import http.server
import socketserver
import sys
import webbrowser
from urllib.parse import urlparse

BASE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
JSON_FILE = BASE / 'grades.json'
PORT = 8000
SHUTDOWN_PASSWORD = os.environ.get('SHUTDOWN_PASSWORD', 'secret')
SERVER_STATE = {'shutting_down': False}


def load_json():
    print(f"[grade-server] load_json: checking {JSON_FILE}")
    if JSON_FILE.exists():
        with JSON_FILE.open('r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                print(f"[grade-server] load_json: loaded data, keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                return data
            except json.JSONDecodeError as e:
                print(f"[grade-server] load_json: JSON decode error: {e}")
                return {}
            except Exception as e:
                print(f"[grade-server] load_json: unexpected error: {e}")
                return {}
    print("[grade-server] load_json: file does not exist")
    return {}


def save_json(data):
    with JSON_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class GradeTrackerHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write((BASE / 'grade-tracker.html').read_text(encoding='utf-8').encode('utf-8'))
            return
        if parsed_path.path == '/api/data':
            print(f"[grade-server] GET /api/data from {self.client_address}")
            data = load_json()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            payload = json.dumps(data)
            try:
                self.wfile.write(payload.encode('utf-8'))
            except BrokenPipeError:
                print("[grade-server] client closed connection before response finished")
            return
        if parsed_path.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(SERVER_STATE).encode('utf-8'))
            return
        # Fall back to serving static files (grade-tracker assets, grades.json, etc.)
        try:
            return super().do_GET()
        except Exception:
            self.send_error(404)

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/api/shutdown':
            content_length = int(self.headers.get('Content-Length', 0))
            provided = None
            if content_length:
                body = self.rfile.read(content_length)
                try:
                    provided = json.loads(body.decode('utf-8')).get('password')
                except Exception:
                    provided = None
            if not provided:
                provided = self.headers.get('X-SHUTDOWN-PASSWORD')
            if provided != SHUTDOWN_PASSWORD:
                self.send_response(403)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': 'invalid password'}).encode('utf-8'))
                return
            SERVER_STATE['shutting_down'] = True
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'shutting_down'}).encode('utf-8'))
            def _shutdown():
                time.sleep(1.0)
                try:
                    self.server.shutdown()
                except Exception:
                    pass
            threading.Thread(target=_shutdown, daemon=True).start()
            return
        if parsed_path.path == '/api/data':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8'))
                save_json(data)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
            return
        self.send_error(404)

    def log_message(self, format, *args):
        # Print requests to console for debugging
        try:
            print("[grade-server] %s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format%args))
        except Exception:
            pass


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_server():
    Handler = lambda *args, **kwargs: GradeTrackerHandler(*args, directory=str(BASE), **kwargs)
    httpd = ThreadedTCPServer(("", PORT), Handler)
    try:
        print(f"Server running at http://localhost:{PORT}")
        print("Opening browser...")
        def open_browser():
            time.sleep(1)
            try:
                webbrowser.open(f'http://localhost:{PORT}')
            except Exception as e:
                print(f"[grade-server] failed to open browser: {e}")
        threading.Thread(target=open_browser, daemon=True).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Server stopped by KeyboardInterrupt.")
        except Exception as e:
            print(f"[grade-server] serve_forever raised: {e}")
    finally:
        try:
            httpd.server_close()
        except Exception:
            pass
        print("Server exiting.")


if __name__ == '__main__':
    run_server()
