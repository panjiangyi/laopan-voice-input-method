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
from unittest.mock import patch
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

    Replays `responses` in order on each DeepSeek /v1/messages hit. Records
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
                if self.path != "/v1/messages":
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
            values.setdefault("DEEPSEEK_API_KEY", "test-key")
            values.setdefault("DEEPSEEK_MODEL", "test-model")
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
    def test_preedit_final_really_calls_deepseek_and_returns_corrected_words(self):
        from concurrent.futures import ThreadPoolExecutor
        from types import SimpleNamespace
        finish = ENGINE["_best_final_text"]
        identity = SimpleNamespace(correct=lambda text: text)
        for enabled, responses, expected in (
            ("1", [{"content": [{"type": "text", "text": "检查 GitHub Actions。"}]}], "检查 GitHub Actions。"),
            ("0", [], "检查 get up actions"),
            ("1", [], "检查 get up actions"),
        ):
            with self.subTest(enabled=enabled, expected=expected), StubServer(responses) as srv:
                with _with_env({
                    "VOICEIME_LLM_ENABLED": enabled,
                    "VOICEIME_LLM_DISABLED": "0",
                    "VOICEIME_LLM_MODE": "aggressive",
                    "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{srv.port}",
                    "VOICEIME_LLM_TIMEOUT": "2",
                }):
                    corrector = Corrector()
                    with patch.dict(finish.__globals__, current_session="test", start_request=1,
                                    terminate=False, final_inflight=None,
                                    set_correction_state=lambda *args: None):
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            result = finish("test", 1, "检查 get up actions", b"",
                                            SimpleNamespace(recognizer=None), identity,
                                            identity, executor, llm=corrector)
                self.assertEqual(result, expected)
                self.assertEqual(len(srv.requests), int(enabled))

    def test_probe_then_correct_sends_expected_payload(self):
        with StubServer([
            {"content": [{"type": "text", "text": "今天，天气很好。"}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENABLED": "1",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "2.0",
                "VOICEIME_LLM_MODE": "punctuation",
            }):
                c = Corrector()
            self.assertTrue(c._available)
            out = c.correct("今天天气很好")
            self.assertEqual(out, "今天，天气很好。")
            self.assertEqual(len(srv.requests), 1)
            req = srv.requests[0]
            self.assertEqual(req["model"], "test-model")
            self.assertEqual(req["temperature"], 0.0)
            self.assertEqual(req["thinking"], {"type": "disabled"})
            self.assertEqual(len(req["messages"]), 1)
            self.assertIn("今天天气很好", req["messages"][0]["content"])

    def test_safe_mode_rejects_chinese_word_substitution(self):
        with StubServer([
            {"content": [{"type": "text", "text": "今天气象很好"}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENABLED": "1",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
                "VOICEIME_LLM_MODE": "punctuation",
            }):
                c = Corrector()
            # The LLM cannot know from text alone whether 气像 or 气象 was spoken.
            # Safe mode therefore preserves the ASR lexical content.
            self.assertEqual(c.correct("今天气像很好"), "今天气像很好")
            self.assertEqual(c.last_status, "rejected")

    def test_timeout_has_distinct_status(self):
        c = Corrector.__new__(Corrector)
        c._available = True
        c.base_url = "http://127.0.0.1:1"
        c.api_key = "test-key"
        c.model = "test-model"
        c.timeout = 0.1
        c.mode = "punctuation"
        c.last_status = "ready"
        with patch("urllib.request.urlopen", side_effect=TimeoutError("slow")):
            self.assertEqual(c.correct("测试"), "测试")
        self.assertEqual(c.last_status, "timeout")

    def test_safe_mode_rejects_deletion_and_rewrite(self):
        with StubServer([
            {"content": [{"type": "text", "text": "我们部署项目。"}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENABLED": "1",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{srv.port}",
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
            {"content": [{"type": "text", "text": "把 GitLab PR merge 到 main。"}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENABLED": "1",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
                "VOICEIME_LLM_MODE": "punctuation",
            }):
                c = Corrector()
            self.assertEqual(
                c.correct("把 GitHub PR merge 到 main"),
                "把 GitHub PR merge 到 main",
            )

    def test_safe_mode_protects_numeric_and_code_symbols(self):
        c = Corrector.__new__(Corrector)
        c.mode = "punctuation"

        unsafe = [
            ("版本是1.5", "版本是15"),
            ("温度是-10", "温度是10"),
            ("用C++实现", "用C实现"),
            ("字段叫user_id", "字段叫userid"),
            ("访问http://a.com", "访问httpa.com"),
        ]
        for original, candidate in unsafe:
            with self.subTest(original=original, candidate=candidate):
                self.assertFalse(c._accept_candidate(original, candidate))

        self.assertTrue(
            c._accept_candidate(
                "这个 API endpoint 要 review 一下",
                "这个API endpoint要 review 一下。",
            )
        )

    def test_aggressive_mode_is_explicit_opt_in(self):
        with StubServer([
            {"content": [{"type": "text", "text": "今天气象很好"}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENABLED": "1",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
                "VOICEIME_LLM_MODE": "aggressive",
            }):
                c = Corrector()
            self.assertEqual(c.correct("今天气像很好"), "今天气象很好")

    def test_unreachable_endpoint_is_safe_fallback(self):
        dead_port = _free_port()
        with _with_env({
            "VOICEIME_LLM_ENABLED": "1",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{dead_port}",
            "VOICEIME_LLM_TIMEOUT": "0.2",
        }):
            dead = Corrector()
        self.assertTrue(dead._available)
        # correct() must NOT raise and must return the input unchanged.
        self.assertEqual(dead.correct("原文不动"), "原文不动")

    def test_disabled_flag_short_circuits(self):
        with _with_env({"VOICEIME_LLM_ENABLED": "0"}):
            with StubServer([]) as srv:
                os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{srv.port}"
                os.environ["DEEPSEEK_API_KEY"] = "test-key"
                os.environ["VOICEIME_LLM_TIMEOUT"] = "1.0"
                c = Corrector()
                self.assertTrue(c._available)
                self.assertEqual(c.correct("原文不动"), "原文不动")
                self.assertEqual(c.last_status, "disabled")
                self.assertEqual(len(srv.requests), 0)

    def test_empty_corrected_text_returns_original(self):
        with StubServer([
            {"content": [{"type": "text", "text": "   "}]},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENABLED": "1",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
            }):
                c = Corrector()
            self.assertTrue(c._available)
            self.assertEqual(c.correct("你好"), "你好")

    def test_malformed_response_returns_original(self):
        with StubServer([
            {"no_content_here": True},
        ]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENABLED": "1",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
            }):
                c = Corrector()
            self.assertTrue(c._available)
            self.assertEqual(c.correct("你好"), "你好")

    def test_empty_text_input_skips_request(self):
        with StubServer([]) as srv:
            with _with_env({
                "VOICEIME_LLM_ENABLED": "1",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{srv.port}",
                "VOICEIME_LLM_TIMEOUT": "1.0",
            }):
                c = Corrector()
            self.assertTrue(c._available)
            self.assertEqual(c.correct(""), "")
            self.assertEqual(c.correct("   "), "   ")
            self.assertEqual(len(srv.requests), 0)


if __name__ == "__main__":
    unittest.main()
