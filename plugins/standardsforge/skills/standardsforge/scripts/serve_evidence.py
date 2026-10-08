"""Preview one saved source sheet in a browser using a loopback-only HTTP URL.

This host-side viewer never opens the database, serves a directory, or fetches content.
Keep the process running while reading; stop it to close the preview.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CONTENT_POLICY = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


def create_server(document: Path, port: int = 0) -> ThreadingHTTPServer:
    if document.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("Select the generated HTML source sheet.")
    content = document.read_bytes()
    content.decode("utf-8-sig")

    class ReaderHandler(BaseHTTPRequestHandler):
        def respond(self, include_body: bool) -> None:
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected_host:
                self.send_error(403, "Use the printed loopback URL.")
                return
            if self.path != "/":
                self.send_error(404, "Only the selected source sheet is available.")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Content-Security-Policy", CONTENT_POLICY)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if include_body:
                self.wfile.write(content)

        def do_GET(self) -> None:
            self.respond(True)

        def do_HEAD(self) -> None:
            self.respond(False)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), ReaderHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="Explicit generated HTML file; neighboring files are not served")
    parser.add_argument("--port", type=int, default=0, help="Local port; default 0 chooses an available port")
    args = parser.parse_args()
    try:
        with create_server(args.document, args.port) as server:
            print(f"http://127.0.0.1:{server.server_port}/", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except (OSError, ValueError, OverflowError) as error:
        parser.exit(2, f"Could not preview evidence: {error}\n")


if __name__ == "__main__":
    main()
