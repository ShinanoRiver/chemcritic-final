"""Password-protected single-team demo entry; local server behavior is unchanged."""
import base64
import binascii
import hmac
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
from http.server import ThreadingHTTPServer

from .server import create_server


def create_cloud_server(agent, origin, username, password, port=10000, db_path=None):
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path not in ('', '/') or parsed.username or parsed.query or parsed.fragment:
        raise ValueError('PUBLIC_ORIGIN must be the HTTPS site origin')
    if not username or ':' in username or len(password) < 16:
        raise ValueError('Demo login requires a username and a password of at least 16 characters')
    expected = (username+':'+password).encode('utf-8')
    local = create_server(0, db_path=db_path, agent=agent)
    parent = local.RequestHandlerClass
    local.server_close()
    lock = threading.Lock()
    submissions = []

    class Handler(parent):
        def log_message(self, format, *args):
            # Avoid request identifiers, headers, or submitted values in cloud logs.
            pass

        def do_GET(self):
            if self.path == '/healthz':
                return self.respond(200, {'status':'ok'})
            return super().do_GET()

        def local_request(self):
            authorization = self.headers.get('Authorization', '')
            try:
                scheme, encoded = authorization.split(' ', 1)
                provided = base64.b64decode(encoded, validate=True) if scheme.lower() == 'basic' else b''
            except (ValueError, binascii.Error):
                provided = b''
            if not hmac.compare_digest(provided, expected):
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="ChemCritic team demo", charset="UTF-8"')
                self.send_header('Content-Length', '0')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                return False
            request_origin = self.headers.get('Origin')
            if self.headers.get('Host') != parsed.netloc or (request_origin is not None and request_origin != origin.rstrip('/')):
                self.close_connection = True
                self.respond(403, {'error':'来源不匹配。'})
                return False
            if self.command == 'POST':
                if request_origin != origin.rstrip('/'):
                    self.close_connection = True
                    self.respond(403, {'error':'提交必须来自本站页面。'})
                    return False
                if self.path in {'/api/agent/reviews','/api/agent/recover'}:
                    with lock:
                        now = time.monotonic()
                        submissions[:] = [t for t in submissions if now-t < 60]
                        if len(submissions) >= 6:
                            self.close_connection = True
                            self.respond(429, {'error':'提交过于频繁，请稍后再试。'})
                            return False
                        submissions.append(now)
            return True

    return ThreadingHTTPServer(('0.0.0.0',port), Handler)


def configured_origin(environ):
    """Railway's generated domain has no scheme; explicit HTTPS origins win."""
    if environ.get('PUBLIC_ORIGIN'):
        return environ['PUBLIC_ORIGIN'].rstrip('/')
    if environ.get('RAILWAY_PUBLIC_DOMAIN'):
        return 'https://' + environ['RAILWAY_PUBLIC_DOMAIN']
    return environ['RENDER_EXTERNAL_URL']


def main():
    from .shared_agent import SharedAgent
    try:
        # Runtime environment only; never print or write the credential.
        agent = SharedAgent(os.environ['SCIENCEPAL_API_KEY'], execution_mode='research')
        origin = configured_origin(os.environ)
        http = create_cloud_server(agent, origin, os.environ['DEMO_USER'], os.environ['DEMO_PASSWORD'],
                                   int(os.environ.get('PORT','10000')),
                                   Path(os.environ.get('DATA_DIR','outputs'))/'chemcritic.sqlite3')
    except (KeyError, ValueError):
        raise SystemExit('Cloud configuration missing or invalid; check server settings. Values are not printed.')
    print('ChemCritic protected team demo started.',flush=True)
    try:
        http.serve_forever()
    finally:
        http.server_close()


if __name__ == '__main__':
    main()
