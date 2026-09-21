"""Unit tests for the engine's LLMCorrector HTTP client.

Uses a stdlib HTTP server stub so the tests don't need GPU, network, or the
real corrector process. Mirrors the runpy + class extraction pattern from
tests/test_engine_logic.py.
"""
import json
import os
import runpy
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = runpy.run_path(str(ROOT / "voiceime-engine"))
Corrector = ENGINE["LLMCorrector"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class StubServer:
    """Tiny test double for the corrector HTTP endpoint.

    Replays `responses` in order on each /v1/chat/completions hit. Records
    every received body in `requests` for assertion.
    """
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self._server = None
        self._thread = None
        self.port = _free_port()

    def __enter__(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args, **_kwargs):
                pass

            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                    return
                self.send_response(404); self.end_headers()

            def do_POST(self):
                if self.path != "/v1/chat/completions":
                    self.send_response(404); self.end_headers(); return
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.requests.append(json.loads(body))
                if not outer.responses:
                    self.send_response(500); self.end_headers(); return
                resp = outer.responses.pop(0)
                body_out = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_out)))
                self.end_headers()
                self.wfile.write(body_out)

        self._server = HTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


def _with_env(values: dict):
    """Context manager that pushes env vars for the duration of a block."""
    class _Ctx:
        def __enter__(self_inner):
            self_inner._saved = {}
            for k, v in values.items():
                self_inner._saved[k] = os.environ.get(k)
                os.environ[k] = v
            return self_inner
        def __exit__(self_inner, *_exc):
            for k, old in self_inner._saved.items():
                if old is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = old
    return _Ctx()


class LLMCorrectorTests(unittest.TestCase):
    def test_probe_then_correct_sends_expected_payload(self):
        with StubServer([
            {"choices": [{"message": {"content": "今天，天气很好。"}}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENDPOINT": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "2.0",
                "VOICEIME_LLM_MODE": "punctuation",
            }):
                c = Corrector()
            self.assertTrue(c._available, "health probe should mark available")
            out = c.correct("今天天气很好")
            self.assertEqual(out, "今天，天气很好。")
            self.assertEqual(len(srv.requests), 1)
            req = srv.requests[0]
            self.assertEqual(req["model"], "local-qwen")
            self.assertEqual(req["temperature"], 0.0)
            self.assertEqual(len(req["messages"]), 2)
            self.assertEqual(req["messages"][0]["role"], "system")
            self.assertEqual(req["messages"][1]["content"], "今天天气很好")

    def test_safe_mode_rejects_chinese_word_substitution(self):
        with StubServer([
            {"choices": [{"message": {"content": "今天气象很好"}}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENDPOINT": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
                "VOICEIME_LLM_MODE": "punctuation",
            }):
                c = Corrector()
            # The LLM cannot know from text alone whether 气像 or 气象 was spoken.
            # Safe mode therefore preserves the ASR lexical content.
            self.assertEqual(c.correct("今天气像很好"), "今天气像很好")

    def test_safe_mode_rejects_deletion_and_rewrite(self):
        with StubServer([
            {"choices": [{"message": {"content": "我们部署项目。"}}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENDPOINT": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
                "VOICEIME_LLM_MODE": "punctuation",
            }):
                c = Corrector()
            self.assertEqual(
                c.correct("那个我们把这个项目部署一下"),
                "那个我们把这个项目部署一下",
            )

    def test_safe_mode_rejects_english_token_changes(self):
        with StubServer([
            {"choices": [{"message": {"content": "把 GitLab PR merge 到 main。"}}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENDPOINT": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
                "VOICEIME_LLM_MODE": "punctuation",
            }):
                c = Corrector()
            self.assertEqual(
                c.correct("把 GitHub PR merge 到 main"),
                "把 GitHub PR merge 到 main",
            )

    def test_aggressive_mode_is_explicit_opt_in(self):
        with StubServer([
            {"choices": [{"message": {"content": "今天气象很好"}}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENDPOINT": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
                "VOICEIME_LLM_MODE": "aggressive",
            }):
                c = Corrector()
            self.assertEqual(c.correct("今天气像很好"), "今天气象很好")

    def test_unreachable_endpoint_is_safe_fallback(self):
        dead_port = _free_port()
        with _with_env({
            "VOICEIME_LLM_ENDPOINT": f"http://127.0.0.1:{dead_port}",
            "VOICEIME_LLM_TIMEOUT": "0.2",
        }):
            dead = Corrector()
        self.assertFalse(dead._available)
        # correct() must NOT raise and must return the input unchanged.
        self.assertEqual(dead.correct("原文不动"), "原文不动")

    def test_disabled_flag_short_circuits(self):
        with _with_env({"VOICEIME_LLM_ENABLED": "0"}):
            with StubServer([]) as srv:
                os.environ["VOICEIME_LLM_ENDPOINT"] = f"http://127.0.0.1:{srv.port}"
                os.environ["VOICEIME_LLM_TIMEOUT"] = "1.0"
                c = Corrector()
                self.assertFalse(c._available)
                self.assertEqual(c.correct("原文不动"), "原文不动")

    def test_empty_corrected_text_returns_original(self):
        with StubServer([
            {"choices": [{"message": {"content": "   "}}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENDPOINT": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
            }):
                c = Corrector()
            self.assertTrue(c._available)
            self.assertEqual(c.correct("你好"), "你好")

    def test_malformed_response_returns_original(self):
        with StubServer([
            {"no_choices_here": True},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENDPOINT": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
            }):
                c = Corrector()
            self.assertTrue(c._available)
            self.assertEqual(c.correct("你好"), "你好")

    def test_empty_text_input_skips_request(self):
        with StubServer([]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENDPOINT": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
            }):
                c = Corrector()
            self.assertTrue(c._available)
            self.assertEqual(c.correct(""), "")
            self.assertEqual(c.correct("   "), "   ")
            self.assertEqual(len(srv.requests), 0)


if __name__ == "__main__":
    unittest.main()