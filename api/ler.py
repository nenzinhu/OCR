import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from tempfile import TemporaryDirectory

from arvc_ia import read_with_ai


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        key = self.headers.get("X-API-Key", "").strip()
        extension = {"image/jpeg": ".jpg", "image/png": ".png",
                     "image/webp": ".webp"}.get(self.headers.get("Content-Type"))
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not key or not extension or not 0 < length <= 3 * 1024 * 1024:
            return self.reply(400, {"error": "Informe a chave do provedor e uma imagem JPG, PNG ou WebP de até 3 MiB."})
        try:
            with TemporaryDirectory() as folder:
                image = Path(folder) / ("arvc" + extension)
                image.write_bytes(self.rfile.read(length))
                source, data = read_with_ai(image, key, self.headers.get("X-Provider", "OpenRouter"),
                                               self.headers.get("X-Model"))
        except RuntimeError as error:
            return self.reply(502, {"error": str(error)})
        self.reply(200, {"source": source, "data": data})

    def reply(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode())
