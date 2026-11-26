import os
import tempfile
import unittest
from pathlib import Path
from threading import Lock
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from audyssey.api import create_app
from audyssey.contracts import SourcePlan
from audyssey.settings import Settings
from audyssey.tools import remote

PLAN = SourcePlan(name="a", kind="sfx", description="a")
TOOLS = ["separator", "filter", "grounder", "generator"]


class GpuToolsTests(unittest.TestCase):
    """`/api/gpu-tools` sets one tool server URL and token for this app process."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.addCleanup(remote.set_override, "", "")
        env = patch.dict(os.environ, {"AUDYSSEY_TOOL_TOKEN": ""})
        env.start()
        self.addCleanup(env.stop)
        self.start_app()

    def start_app(self, **settings):
        self.app = create_app(Settings(work_dir=self.root / "jobs", **settings))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        for name in ["m.wav", "t.wav"]:
            (self.root / name).write_bytes(b"x")

    def save(self, url, token=None):
        return self.client.post("/api/gpu-tools", json={"tools_url": url, "token": token})

    def separate_call(self):
        """Run the app's separate tool against a mocked server; return (url, headers)."""
        response = httpx.Response(200, content=b"wav", request=httpx.Request("POST", "http://x"))
        with patch("audyssey.tools.remote.httpx.post", return_value=response) as post:
            self.app.state.ctx.tools.separate(self.root / "m.wav", PLAN, None, self.root / "o.wav", 1)
        (url,), kwargs = post.call_args
        return str(url), kwargs["headers"]

    def test_default_is_empty_and_stub(self):
        body = self.client.get("/api/gpu-tools").json()
        self.assertEqual(body, {"tools_url": "", "token_set": False, "remote": dict.fromkeys(TOOLS, False)})

    def test_save_switches_all_four_tools_to_remote(self):
        response = self.save("http://gpu:8700/", "tok")
        self.assertEqual(response.status_code, 200, response.text)
        expected = {"tools_url": "http://gpu:8700", "token_set": True, "remote": dict.fromkeys(TOOLS, True)}
        self.assertEqual(response.json(), expected)
        self.assertEqual(self.client.get("/api/gpu-tools").json(), expected)
        self.assertEqual(self.separate_call(), ("http://gpu:8700/separate", {"Authorization": "Bearer tok"}))

    def test_token_never_appears_in_responses(self):
        for response in [self.save("http://gpu:8700", "secret-token"), self.client.get("/api/gpu-tools"), self.client.get("/api/system")]:
            self.assertNotIn("secret-token", response.text)

    def test_invalid_urls_are_rejected_and_change_nothing(self):
        for url in ["gpu:8700", "ftp://gpu", "http://", "http://user:pw@gpu:8700", "javascript:alert(1)"]:
            with self.subTest(url=url):
                self.assertEqual(self.save(url, "tok").status_code, 422)
        self.assertEqual(self.client.get("/api/gpu-tools").json()["tools_url"], "")
        self.assertFalse(self.client.get("/api/gpu-tools").json()["token_set"])

    def test_empty_url_clears_url_and_token(self):
        self.save("http://gpu:8700", "tok")
        body = self.save("").json()
        self.assertEqual(body, {"tools_url": "", "token_set": False, "remote": dict.fromkeys(TOOLS, False)})

    def test_null_token_keeps_the_current_token(self):
        self.save("http://gpu:8700", "tok")
        self.save("http://other:8700", None)
        self.assertEqual(self.separate_call(), ("http://other:8700/separate", {"Authorization": "Bearer tok"}))

    def test_empty_token_drops_the_saved_token(self):
        self.save("http://gpu:8700", "tok")
        response = self.save("http://gpu:8700", "")
        self.assertFalse(response.json()["token_set"])
        self.assertEqual(self.separate_call()[1], {})

    def test_override_beats_env_and_env_is_the_fallback(self):
        env = {"AUDYSSEY_SEPARATOR_URL": "http://env:1", "AUDYSSEY_TOOL_TOKEN": "env-tok", "AUDYSSEY_SEPARATOR": "remote"}
        with patch.dict(os.environ, env):
            self.start_app(separator="remote", separator_url="http://env:1", tool_token="env-tok")
            body = self.client.get("/api/gpu-tools").json()
            self.assertEqual(body["remote"], {**dict.fromkeys(TOOLS, False), "separator": True})
            self.assertTrue(body["token_set"])
            self.assertEqual(self.separate_call(), ("http://env:1/separate", {"Authorization": "Bearer env-tok"}))
            self.save("http://gpu:8700", "")
            self.assertEqual(self.separate_call(), ("http://gpu:8700/separate", {"Authorization": "Bearer env-tok"}))
            self.save("http://gpu:8700", "ui-tok")
            self.assertEqual(self.separate_call()[1], {"Authorization": "Bearer ui-tok"})
            self.save("")
            self.assertEqual(self.separate_call(), ("http://env:1/separate", {"Authorization": "Bearer env-tok"}))

    def test_judge_client_uses_the_override(self):
        self.save("http://gpu:8700", "tok")
        tools = self.app.state.ctx.tools
        ok = httpx.Response(200, json={"passed": True}, request=httpx.Request("POST", "http://x"))
        with patch("audyssey.tools.remote.httpx.post", return_value=ok) as post:
            tools.judge(self.root / "m.wav", self.root / "t.wav", PLAN)
        self.assertEqual(str(post.call_args.args[0]), "http://gpu:8700/judge")

    def test_changing_while_a_job_is_busy_is_refused(self):
        lock = self.app.state.locks.setdefault("job", Lock())
        with lock:
            self.assertEqual(self.save("http://gpu:8700", "tok").status_code, 409)
            self.assertEqual(self.client.get("/api/gpu-tools").json()["tools_url"], "")
        self.assertEqual(self.save("http://gpu:8700", "tok").status_code, 200)

    def test_system_status_follows_the_override(self):
        self.save("http://gpu:8700", "tok")
        ok = httpx.Response(200, request=httpx.Request("GET", "http://x"))
        with patch("audyssey.api.httpx.get", return_value=ok) as get:
            lanes = self.client.get("/api/system").json()
        self.assertIn("tool:gpu:8700", [lane["id"] for lane in lanes])
        self.assertEqual(get.call_args.args[0], "http://gpu:8700/health")


if __name__ == "__main__":
    unittest.main()
