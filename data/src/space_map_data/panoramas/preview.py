"""Serve a local panorama preview and its derived assets."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from space_map_data.utils.paths import DERIVED_DIR


class PreviewHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/":
            content = Path(__file__).with_name("preview.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            super().do_GET()


def main():
    parser = argparse.ArgumentParser(
        description="Preview processed planetary panoramas locally"
    )
    parser.add_argument("--directory", type=Path, default=DERIVED_DIR / "panoramas")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_dir():
        parser.error(f"Missing panorama directory: {directory}")
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), partial(PreviewHandler, directory=str(directory))
    )
    print(f"Panorama preview: http://localhost:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
