import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from fastapi.testclient import TestClient
from tests.audyssey_media import make_video
from audyssey.api import create_app
from audyssey.settings import Settings


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = make_video(self.root / "clip.mp4")
        self.app = create_app(Settings(work_dir=self.root / "jobs"))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def upload(self, name="clip.mp4"):
        response = self.client.post(
            "/api/jobs",
            files={"file": (name, self.video.read_bytes(), "video/mp4")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def wait(self, job_id, state):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = self.client.get(f"/api/jobs/{job_id}").json()
            if job["state"] != "running":
                self.assertEqual(job["state"], state, job)
                return job
            time.sleep(0.1)
        self.fail("analysis timed out")

    def ready(self, name="clip.mp4", method="separate"):
        job_id = self.upload(name)
        self.wait(job_id, "new")
        response = self.client.post(f"/api/jobs/{job_id}/start", json={"method": method})
        self.assertEqual(response.status_code, 200, response.text)
        return self.wait(job_id, "ready")

    def test_upload_runs_analysis_to_ready(self):
        self.assertEqual(len(self.ready()["sources"]), 3)
        self.assertEqual(len(self.client.get("/api/jobs").json()), 1)

    def test_upload_waits_for_start(self):
        job = self.wait(self.upload(), "new")
        self.assertEqual([s["key"] for s in job["steps"]], ["preprocess"])
        self.assertEqual(job["sources"], [])

    def test_commands_use_job_updated_by_studio_graph(self):
        from audyssey.graph import build_graph

        job_id = self.upload()
        self.wait(job_id, "new")
        result = build_graph(self.app.state.ctx).invoke({"job_id": job_id})
        self.assertEqual(result["job"].state, "ready")
        response = self.command(
            job_id, {"type": "set_gain", "source_id": "s1", "gain": 0.5}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sources"][0]["gain"], 0.5)

    def test_start_twice_is_rejected(self):
        job = self.ready()
        response = self.client.post(f"/api/jobs/{job['id']}/start", json={"method": "separate"})
        self.assertEqual(response.status_code, 409)

    def test_generate_start_generates_every_source(self):
        job = self.ready(method="generate")
        self.assertEqual(job["method"], "generate")
        self.assertTrue(all(s["origin"] == "generated" for s in job["sources"]))
        self.assertIsNone(job["residual"]["path"])

    def test_silent_video_cannot_start_separation(self):
        self.video = make_video(self.root / "silent.mp4", audio=False)
        job = self.wait(self.upload("silent.mp4"), "new")
        response = self.client.post(f"/api/jobs/{job['id']}/start", json={"method": "separate"})
        self.assertEqual(response.status_code, 422)

    def test_upload_accepts_no_audio(self):
        self.video = make_video(self.root / "silent.mp4", audio=False)
        job = self.ready("silent.mp4", method="generate")
        self.assertTrue(job["silent"])
        self.assertIsNone(job["residual"]["path"])

    def test_upload_rejects_too_large(self):
        self.app.state.ctx.settings.max_upload_mb = len(self.video.read_bytes()) / 2 / 2**20
        response = self.client.post(
            "/api/jobs", files={"file": ("clip.mp4", self.video.read_bytes())}
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.get("/api/jobs").json(), [])

    def test_upload_html_name_is_served_as_video(self):
        job = self.ready("page.html")
        self.assertEqual(job["video_path"], "input.mp4")
        served = self.client.get(f"/api/jobs/{job['id']}/files/input.mp4")
        self.assertEqual(served.headers["content-type"], "video/mp4")

    def test_upload_rejects_too_long(self):
        self.app.state.ctx.settings.max_duration_s = 2
        response = self.client.post(
            "/api/jobs", files={"file": ("clip.mp4", self.video.read_bytes())}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("maximum is 2s", response.json()["detail"])
        self.assertEqual(self.client.get("/api/jobs").json(), [])

    def test_files_traversal_404(self):
        job = self.ready()
        for path in ["..%2F..%2Fetc%2Fpasswd", "missing.wav"]:
            self.assertEqual(
                self.client.get(f"/api/jobs/{job['id']}/files/{path}").status_code, 404
            )
        self.assertGreater(
            len(self.client.get(f"/api/jobs/{job['id']}/files/audio.wav").content), 0
        )
        self.assertEqual(self.client.get("/api/jobs/000000000000").status_code, 404)

    def test_events_first_message_is_job(self):
        job = self.ready()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(
                uvicorn.Config(self.app, log_level="error", ws="none")
            )
            thread = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not server.started and time.monotonic() < deadline:
                    time.sleep(0.01)
                with httpx.stream(
                    "GET",
                    f"http://127.0.0.1:{port}/api/jobs/{job['id']}/events",
                    timeout=5,
                ) as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("text/event-stream", response.headers["content-type"])
                    line = next(response.iter_lines())
                    self.assertEqual(
                        json.loads(line.removeprefix("data: "))["id"], job["id"]
                    )
            finally:
                server.should_exit = True
                thread.join(timeout=5)

    def command(self, job_id, data):
        return self.client.post(f"/api/jobs/{job_id}/commands", json=data)

    def test_command_render_and_download(self):
        job = self.ready()
        response = self.command(job["id"], {"type": "render"})
        self.assertEqual(response.status_code, 200, response.text)
        path = response.json()["outputs"]["video_mp4"]
        download = self.client.get(f"/api/jobs/{job['id']}/files/{path}")
        self.assertEqual(download.status_code, 200)
        self.assertGreater(len(download.content), 0)

    def test_final_state_is_saved_after_the_job_lock_is_released(self):
        # A client that sees "ready" may send an execution command at once; the
        # lock must already be free by then, or the command gets 409.
        store = self.app.state.ctx.store
        save, held = store.save, []

        def checking_save(job):
            if job.state != "running":
                held.append(self.app.state.locks[job.id].locked())
            return save(job)

        with patch.object(store, "save", checking_save):
            job = self.ready()
            self.assertEqual(held, [False, False])
            response = self.command(job["id"], {"type": "render"})
        self.assertEqual(response.status_code, 200, response.text)

    def test_command_conflict_while_busy(self):
        job = self.ready()
        with self.app.state.locks[job["id"]]:
            response = self.command(
                job["id"], {"type": "reseparate", "source_id": "s1"}
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"], "job is busy")
            response = self.command(
                job["id"], {"type": "set_gain", "source_id": "s1", "gain": 0.5}
            )
            self.assertEqual(response.status_code, 200)
        # A later execution must preserve the edit made while the job was busy.
        response = self.command(job["id"], {"type": "reseparate", "source_id": "s2"})
        self.assertEqual(response.json()["sources"][0]["gain"], 0.5)

    def test_command_errors(self):
        job = self.ready()
        for data, status in [
            ({"type": "unknown"}, 422),
            ({"type": "drop", "source_id": "s99"}, 404),
            (
                {
                    "type": "add_source",
                    "plan": {
                        "name": "bad",
                        "kind": "sfx",
                        "description": "sound",
                        "spans": [{"start": 0, "end": 4}],
                    },
                },
                422,
            ),
            ({"type": "set_pitch", "source_id": "residual", "semitones": 1}, 422),
            ([], 422),
        ]:
            before = self.client.get(f"/api/jobs/{job['id']}").json()
            self.assertEqual(self.command(job["id"], data).status_code, status)
            self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").json(), before)

    def test_root_serves_demo_ui_and_dev_ui_moves(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="board"', response.text)
        self.assertIn("내보내기", response.text)
        self.assertIn("Audyssey dev UI", self.client.get("/dev").text)

    def test_trace_records_each_step_with_its_server(self):
        job = self.ready()
        self.command(job["id"], {"type": "render"})
        calls = self.client.get(f"/api/jobs/{job['id']}/trace").json()
        tools = [c["tool"] for c in calls]
        self.assertEqual(tools[:3], ["preprocess", "plan", "validate_plan"])
        # Stub judging fails one source once, so it is separated twice.
        separated = {c["step"] for c in calls if c["tool"] == "separate"}
        self.assertEqual(separated, {"separate:s1", "separate:s2", "separate:s3"})
        self.assertEqual(tools[-2:], ["residual", "render"])
        separate = next(c for c in calls if c["tool"] == "separate")
        self.assertEqual(separate["step"], "separate:s1")
        self.assertEqual(separate["server"], "App server")
        self.assertEqual(separate["inputs"]["plan"]["name"], job["sources"][0]["plan"]["name"])
        # Outputs are snapshotted so retries that overwrite the track keep this one.
        snapshot = separate["output"]["file"]
        self.assertTrue(snapshot.startswith(f"trace/{separate['id']}/"))
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/files/{snapshot}").status_code, 200)
        render = calls[-1]["output"]
        self.assertEqual(render["video"], {"file": "out/video.mp4"})
        self.assertEqual(self.client.get("/api/jobs/0123456789ab/trace").status_code, 404)

    def test_system_lists_servers_in_pipeline_order(self):
        lanes = self.client.get("/api/system").json()
        self.assertEqual([lane["id"] for lane in lanes], ["app"])
        self.assertTrue(lanes[0]["up"])
        self.assertEqual(lanes[0]["steps"][0], "preprocess")
        self.assertEqual(lanes[0]["steps"][-1], "render")

    def test_system_checks_openrouter_key_with_configured_url(self):
        settings = Settings(
            work_dir=self.root / "jobs",
            planner="real",
            planner_base_url="https://openrouter.ai/api/v1/",
            planner_api_key="test-openrouter-key",
        )
        with TestClient(create_app(settings)) as client, patch(
            "audyssey.api.httpx.get", return_value=httpx.Response(200)
        ) as request:
            response = client.get("/api/system")
        lane = next(lane for lane in response.json() if "plan" in lane["steps"])
        self.assertEqual((lane["name"], lane["up"]), ("OpenRouter", True))
        request.assert_called_once_with(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": "Bearer test-openrouter-key"},
            timeout=3,
        )
        self.assertNotIn("test-openrouter-key", response.text)

    def test_system_reports_rejected_openrouter_key(self):
        settings = Settings(
            work_dir=self.root / "jobs",
            planner="real",
            planner_base_url="https://openrouter.ai/api/v1",
            planner_api_key="invalid-key",
        )
        with TestClient(create_app(settings)) as client, patch(
            "audyssey.api.httpx.get", return_value=httpx.Response(401)
        ):
            response = client.get("/api/system")
        lane = next(lane for lane in response.json() if "plan" in lane["steps"])
        self.assertFalse(lane["up"])

    def test_system_preserves_llm_scheme_base_path_and_authentication(self):
        settings = Settings(
            work_dir=self.root / "jobs",
            planner="real",
            planner_base_url="https://inference.example/proxy/v1",
            planner_api_key="test-proxy-key",
        )
        with TestClient(create_app(settings)) as client, patch(
            "audyssey.api.httpx.get", return_value=httpx.Response(200)
        ) as request:
            response = client.get("/api/system")
        lane = next(lane for lane in response.json() if "plan" in lane["steps"])
        self.assertTrue(lane["up"])
        request.assert_called_once_with(
            "https://inference.example/proxy/v1/models",
            headers={"Authorization": "Bearer test-proxy-key"},
            timeout=3,
        )

    def test_system_handles_unconfigured_llm_url(self):
        settings = Settings(work_dir=self.root / "jobs", planner="real")
        with TestClient(create_app(settings)) as client, patch(
            "audyssey.api.httpx.get"
        ) as request:
            response = client.get("/api/system")
        self.assertEqual(response.status_code, 200)
        lane = next(lane for lane in response.json() if "plan" in lane["steps"])
        self.assertFalse(lane["up"])
        request.assert_not_called()

    def test_export_zips_render_outputs(self):
        import io
        import zipfile

        job = self.ready()
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/export").status_code, 409)
        self.command(job["id"], {"type": "render"})
        response = self.client.get(f"/api/jobs/{job['id']}/export")
        self.assertEqual(response.status_code, 200)
        names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
        self.assertIn("video.mp4", names)
        self.assertIn("mix.wav", names)
        self.assertTrue(any(n.startswith("stems/") for n in names))

    def test_generation_command_errors_are_422(self):
        job = self.ready()
        for command in [
            {"type": "generate", "source_id": "s1"},
            {"type": "generate", "source_id": "residual"},
            {"type": "add_source", "method": "generate", "plan": {"name": "voice", "kind": "dialogue", "description": "voice"}},
        ]:
            before = self.client.get(f"/api/jobs/{job['id']}").json()
            response = self.command(job["id"], command)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").json(), before)
        response = self.command(job["id"], {"type": "generate", "source_id": "s3"})
        self.assertEqual(response.status_code, 200, response.text)
        generated = response.json()["sources"][-1]
        response = self.command(job["id"], {"type": "reseparate", "source_id": generated["id"]})
        self.assertEqual(response.status_code, 422, response.text)

    def test_silent_separation_commands_are_422(self):
        self.video = make_video(self.root / "silent.mp4", audio=False)
        job = self.ready(method="generate")
        for command in [
            {"type": "reseparate", "source_id": "s3"},
            {"type": "add_source", "plan": {"name": "extra", "kind": "sfx", "description": "sound"}},
        ]:
            response = self.command(job["id"], command)
            self.assertEqual(response.status_code, 422, response.text)

    def test_generate_is_an_execution_command(self):
        job = self.ready()
        with self.app.state.locks[job["id"]]:
            response = self.command(job["id"], {"type": "generate", "source_id": "s3"})
        self.assertEqual(response.status_code, 409, response.text)
        response = self.command(job["id"], {"type": "generate", "source_id": "s3"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sources"][-1]["origin"], "generated")
