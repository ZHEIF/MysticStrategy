from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import analyze, clamp_text


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        return

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        payload = self._read_json()
        mode = clamp_text(payload.get("mode"), 16).lower()
        if mode not in {"self", "friends"}:
            self._send_json({"ok": False, "error": "mode must be self or friends"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            self._send_json(analyze(mode, payload))
        except Exception as exc:
            self._send_json(
                {"ok": False, "source": "deepseek", "error": f"DeepSeek 深度思考请求失败：{exc}"},
                HTTPStatus.BAD_GATEWAY,
            )

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
