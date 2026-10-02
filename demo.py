#!/usr/bin/env python3
"""Launch the local SDS Performance Investigator."""
import argparse
import fcntl
import json
import mimetypes
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from engine import Manager, ROOT, preflight
from revisions import versions, commit_range

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, manager):
        super().__init__(address, Handler)
        self.manager = manager
        self.token = secrets.token_urlsafe(32)
        self.origin = f'http://127.0.0.1:{self.server_port}'

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, value, status=200, content_type='application/json', filename=None):
        body = json.dumps(value).encode() if content_type == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def trusted(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}' and self.headers.get('Origin', self.server.origin) == self.server.origin

    def do_GET(self):
        if not self.trusted():
            return self.send({'error': 'Untrusted host or origin'}, 403)
        path = urlparse(self.path).path
        try:
            if path == '/api/config':
                choices = []
                for directory in ROOT.parent.iterdir():
                    if (directory/'sds/Cargo.toml').exists() and (directory/'.git').exists():
                        choices.append(str(directory))
                return self.send({'token': self.server.token, 'repositories': sorted(choices), 'active': self.server.manager.active})
            if path.startswith('/api/commit-summaries/'):
                return self.send(self.server.manager.summaries.get(path.split('/')[-1]))
            if path == '/api/runs':
                return self.send(self.server.manager.history())
            if path.startswith('/api/runs/'):
                parts = path.split('/')
                run_id = parts[3]
                if len(parts) == 4:
                    return self.send(self.server.manager.get(run_id))
                if parts[4] == 'analysis':
                    analysis = self.server.manager.analysis
                    query = parse_qs(urlparse(self.path).query)
                    attempt = query.get('attempt', [None])[0]
                    if len(parts) == 5:
                        return self.send(analysis.get(run_id, attempt))
                    if len(parts) == 6 and parts[5] == 'evidence':
                        return self.send(analysis.evidence(run_id, query.get('file', [''])[0], int(query.get('start', ['0'])[0]), int(query.get('end', ['0'])[0])))
                    if len(parts) == 6 and parts[5] == 'report':
                        state = analysis.get(run_id, attempt)
                        return self.send(analysis.report(run_id, state.get('id', '')).encode(), content_type='text/plain; charset=utf-8', filename='agent-analysis.md')
                    raise ValueError('Unknown analysis endpoint')
                folder = self.server.manager.directory(run_id)
                if parts[4] == 'log':
                    log = folder/'run.log'
                    if not log.exists():
                        return self.send({'text': ''})
                    with log.open('rb') as stream:
                        stream.seek(max(0, log.stat().st_size-64000))
                        return self.send({'text': stream.read().decode(errors='replace')})
                if len(parts) == 6 and parts[4] == 'download' and parts[5] in ('report.md', 'results.json', 'investigate.md', 'changes.diff'):
                    return self.send((folder/parts[5]).read_bytes(), content_type='text/plain; charset=utf-8', filename=parts[5])
                raise ValueError('Unknown artifact')
            files = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
            if path not in files:
                return self.send({'error': 'Not found'}, 404)
            file = ROOT/'static'/files[path]
            return self.send(file.read_bytes(), content_type=(mimetypes.guess_type(file)[0] or 'text/plain')+'; charset=utf-8')
        except (ValueError, OSError) as exc:
            self.send({'error': str(exc)}, 404)

    def do_POST(self):
        supplied = self.headers.get('X-Launch-Token', '').encode('utf-8')
        if not self.trusted() or not secrets.compare_digest(supplied, self.server.token.encode('utf-8')):
            return self.send({'error': 'Invalid origin or launch token'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                raise ValueError('Invalid request size')
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise ValueError('Expected a JSON object')
            if self.path == '/api/revisions':
                return self.send(versions(request.get('repo'), request.get('skip', 0), demo=request.get('demo') is True))
            if self.path == '/api/commit-range':
                return self.send(commit_range(request.get('repo'), request.get('base'), request.get('candidate'), demo=request.get('demo') is True))
            if self.path == '/api/commit-summaries':
                return self.send(self.server.manager.summaries.start(request))
            if self.path == '/api/commit-summaries/cancel':
                if self.server.manager.summaries.active != request.get('id'):
                    raise ValueError('This summary job is not active')
                self.server.manager.summaries.cancel.set()
                return self.send({'ok': True})
            if self.path == '/api/preflight':
                return self.send(preflight(request))
            if self.path == '/api/runs':
                return self.send(self.server.manager.start(request), 201)
            parts = self.path.split('/')
            if len(parts) == 5 and parts[1:3] == ['api', 'runs'] and parts[4] == 'analysis':
                return self.send(self.server.manager.analysis.start(parts[3]), 201)
            if len(parts) == 6 and parts[1:3] == ['api', 'runs'] and parts[4:] == ['analysis', 'cancel']:
                self.server.manager.analysis.cancel(parts[3]); return self.send({'ok': True})
            if len(parts) == 5 and parts[1:3] == ['api', 'runs'] and parts[4] == 'cancel':
                self.server.manager.cancel(parts[3]); return self.send({'ok': True})
            self.send({'error': 'Not found'}, 404)
        except (ValueError, OSError) as exc:
            self.send({'error': str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    lock = (ROOT/'.server.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Another investigator is already running from this directory')
    manager = Manager()
    server = Server(('127.0.0.1', args.port), manager)
    print(f'SDS Performance Investigator: {server.origin}', flush=True)
    print('Local only. Press Ctrl+C to stop. Runs are saved under perf-investigator/runs.', flush=True)
    if not args.no_browser:
        threading.Timer(.3, lambda: webbrowser.open(server.origin)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        manager.cancel_event.set()
        manager.summaries.cancel.set()
        if manager.summaries.thread:
            manager.summaries.thread.join(timeout=5)
        if manager.thread:
            manager.thread.join(timeout=5)
        server.server_close()
        lock.close()

if __name__ == '__main__':
    main()
