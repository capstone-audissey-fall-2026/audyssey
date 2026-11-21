import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import httpx2
from google import genai
from google.genai import types

from audyssey.contracts import PlanIssue, SourcePlan
from audyssey.tools.planning import real
from audyssey.tools.planning.llm import chat_client


class PlannerRealTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.image = self.root / "frame.jpg"
        self.image.write_bytes(b"\xff\xd8test-jpeg")
        self.video, self.audio = self.root / "video.mp4", self.root / "audio.wav"
        self.video.write_bytes(b"private-video-bytes")
        import numpy as np
        from audyssey.media import write_wav
        write_wav(self.audio, 0.2 * np.sin(2 * np.pi * 440 * np.arange(96000) / 48000))
        self.requests = []
        self.responses = []
        # Windows/OpenSSL needs its system directory even with mocked HTTP.
        runtime = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR"}}
        env = patch.dict(os.environ, {**runtime,
            "AUDYSSEY_PLANNER_BASE_URL": "http://test.invalid/v1",
            "AUDYSSEY_PLANNER_MODEL": "fake-model",
            "AUDYSSEY_PLANNER_API_KEY": "fake-key",
            "LANGSMITH_TRACING": "false",
            "AUDYSSEY_VALIDATOR_AUDIO_ONLY": "false",
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        frames = patch("audyssey.media.extract_frames", return_value=[
            (0.25, self.image), (1.25, self.image),
        ])
        self.frames = frames.start()
        self.addCleanup(frames.stop)
        probe = patch("audyssey.media.probe", return_value=(2.0, 2))
        probe.start()
        self.addCleanup(probe.stop)
        # The real SDK serializes the request; only the network is replaced.
        client = patch("audyssey.tools.planning.llm.chat_client", side_effect=lambda settings: chat_client(
            settings, transport=httpx2.MockTransport(self.respond)
        ))
        client.start()
        self.addCleanup(client.stop)

    def respond(self, request):
        self.requests.append(json.loads(request.content))
        content = self.responses.pop(0)
        return httpx2.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0,
            "model": "fake-model", "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}, "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }],
        })

    def source(self, **updates):
        return {"name": "person", "kind": "dialogue", "description": "a person speaking", **updates}

    def plan(self, sources, feedback=None):
        self.responses.append(json.dumps({"sources": sources}))
        return real.plan(self.video, self.audio, 2, feedback or [])

    def test_planner_sees_accepted_sources_and_instruction(self):
        from audyssey.tools.planning import planning_scope
        accepted = (SourcePlan(**self.source(name="door", kind="sfx", description="a door slams")),)
        with planning_scope("separate", True, accepted):
            self.plan([self.source()])
        request = self.requests[0]
        context = request["messages"][1]["content"][0]["text"]
        self.assertIn('"accepted_sources": [{"name": "door"', context)
        self.assertIn("accepted_sources", request["messages"][0]["content"])
        self.assertIn("do not return them again", request["messages"][0]["content"].lower())

    def test_plan_accepts_bare_source_list(self):
        # Gemini sometimes returns the list without the {"sources": ...} wrapper.
        self.responses.append(json.dumps([self.source()]))
        result = real.plan(self.video, self.audio, 2, [])
        self.assertEqual([p.name for p in result], ["person"])
        self.assertEqual(len(self.requests), 1)

    def test_plan_parses_sources_and_clamps(self):
        result = self.plan([self.source(
            spans=[{"start": -1, "end": 5}, {"start": 3, "end": 4}, {"start": 1, "end": 0}],
            visual_hint={"time": 5, "box": [-0.1, 0.2, 1.5, 0.8], "description": "person"},
        )])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], SourcePlan)
        self.assertEqual([(s.start, s.end) for s in result[0].spans], [(0, 2)])
        self.assertEqual(result[0].visual_hint.box, (0, 0.2, 1, 0.8))
        self.assertEqual(result[0].visual_hint.time, 2)
        result = self.plan([self.source(visual_hint={
            "time": 0, "box": [2, 0, 3, 1], "description": "invalid box",
        })])
        self.assertIsNone(result[0].visual_hint)

    def test_plan_retries_once_on_bad_json(self):
        self.responses.append("broken")
        self.assertEqual(self.plan([self.source()])[0].name, "person")
        self.assertEqual(len(self.requests), 2)
        self.requests.clear()
        for bad in ["x" * 600, '{}', '{"sources": null}', None]:
            with self.subTest(bad=bad):
                self.responses = [bad, bad]
                with self.assertRaisesRegex(RuntimeError, "planner returned invalid JSON") as caught:
                    real.plan(self.video, self.audio, 2, [])
                self.assertLessEqual(len(str(caught.exception)), 532)
        self.assertEqual(len(self.requests), 8)
        # A bare empty list is a valid but empty source list, like {"sources": []}.
        self.responses = ['[]']
        self.assertEqual(real.plan(self.video, self.audio, 2, []), [])
        self.assertEqual(len(self.requests), 9)

    def test_plan_drops_invalid_items_and_errors_when_none_left(self):
        invalid = [None, 3, {}, self.source(kind="unknown"), self.source(spans="bad"), self.source(spans=[{"start": float("nan"), "end": 1}])]
        self.assertEqual([s.name for s in self.plan([*invalid, self.source()])], ["person"])
        with self.assertRaisesRegex(RuntimeError, "no valid sources"):
            self.plan(invalid)

    def test_plan_includes_feedback_and_frame_times_in_prompt(self):
        feedback = [PlanIssue(source_name="ghost", kind="missing", message="remove ghost exactly")]
        self.plan([self.source()], feedback)
        request = self.requests[0]
        self.assertEqual(request["model"], "fake-model")
        self.assertEqual(request["response_format"], {"type": "json_object"})
        parts = request["messages"][1]["content"]
        text = "\n".join(part["text"] for part in parts if part["type"] == "text")
        self.assertIn(json.dumps([feedback[0].model_dump()]), text)
        for expected in ["0.25", "1.25", "2"]:
            self.assertIn(expected, text)

    def test_plan_sends_images_not_video_or_audio(self):
        self.plan([self.source()])
        parts = self.requests[0]["messages"][1]["content"]
        images = [part["image_url"]["url"] for part in parts if part["type"] == "image_url"]
        self.assertEqual(len(images), 2)
        for url in images:
            self.assertTrue(url.startswith("data:image/jpeg;base64,"))
            self.assertEqual(base64.b64decode(url.split(",")[1]), self.image.read_bytes())
        wire = json.dumps(self.requests)
        for data in [self.video.read_bytes(), self.audio.read_bytes()]:
            self.assertNotIn(base64.b64encode(data).decode(), wire)
        self.assertNotIn(self.video.read_bytes().decode(), wire)

    def test_plan_samples_frames_by_fps_up_to_cap(self):
        for env, count in [({"AUDYSSEY_PLANNER_FPS": "3"}, 6), ({"AUDYSSEY_PLANNER_FPS": "3", "AUDYSSEY_PLANNER_MAX_FRAMES": "4"}, 4),
                           ({"AUDYSSEY_PLANNER_FPS": "0.1"}, 1)]:
            with self.subTest(env=env), patch.dict(os.environ, env):
                self.frames.reset_mock()
                self.plan([self.source()])
                args = self.frames.call_args.args
                self.assertEqual((args[1], args[3], args[4]), (count, 0, 2))

    def clip(self, windows=False):
        self.windows = windows
        calls = []

        def write(video, out, audio, start=0, end=None):
            calls.append((audio, start, end) if self.windows else audio)
            out.write_bytes(b"clip-bytes")
            return out

        clip = patch("audyssey.media.planner_clip", side_effect=write)
        clip.start()
        self.addCleanup(clip.stop)
        return calls

    def test_video_input_sends_one_video_with_fps(self):
        calls = self.clip()
        encoded = base64.b64encode(b"clip-bytes").decode()
        for audio in (False, True):
            env = {"AUDYSSEY_PLANNER_INPUT": "video", "AUDYSSEY_PLANNER_FPS": "2",
                   "AUDYSSEY_PLANNER_VIDEO_AUDIO": str(audio).lower()}
            with self.subTest(audio=audio), patch.dict(os.environ, env):
                self.requests.clear()
                self.plan([self.source()])
                request = self.requests[0]
                parts = request["messages"][1]["content"]
                self.assertEqual([p["type"] for p in parts], ["text", "text", "video_url"])
                self.assertEqual(parts[1]["text"], "Video from 0 to 2 seconds")
                self.assertEqual(parts[2]["video_url"]["url"], "data:video/mp4;base64," + encoded)
                self.assertEqual(request["media_io_kwargs"], {"video": {"fps": 2.0, "num_frames": -1}})
                self.assertEqual(request.get("mm_processor_kwargs"),
                                 {"use_audio_in_video": True} if audio else None)
                self.assertEqual(calls[-1], audio)
                self.assertEqual("audio track" in request["messages"][0]["content"], audio)

    def respond_gemini(self, request):
        url = str(request.url)
        self.gemini_calls.append((request.method, url, request.headers.get("x-goog-api-key")))
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        if "/upload/" in url and url.endswith("/files"):
            self.uploads.append(dict(request.headers))
            return httpx.Response(200, headers={"x-goog-upload-url": "https://gemini.test/upload/session-1"})
        if url.endswith("/upload/session-1"):
            self.uploaded.append(request.content)
            return httpx.Response(200, headers={"x-goog-upload-status": "final"}, json={"file": {
                "name": "files/abc", "uri": "https://gemini.test/v1beta/files/abc", "state": "PROCESSING"}})
        if url.endswith("/files/abc"):
            return httpx.Response(200, json={
                "name": "files/abc", "uri": "https://gemini.test/v1beta/files/abc", "state": "ACTIVE"})
        self.requests.append({"url": url, **json.loads(request.content)})
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": self.responses.pop(0)}]}}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 5, "totalTokenCount": 8},
        })

    def gemini(self, respond):
        """Real SDK, fake network: the SDK serializes uploads and requests itself."""
        self.gemini_calls, self.uploads, self.uploaded = [], [], []
        return patch("audyssey.tools.planning.llm.gemini_client", side_effect=lambda endpoint: genai.Client(
            api_key=endpoint.api_key,
            http_options=types.HttpOptions(httpx_client=httpx.Client(transport=httpx.MockTransport(respond))),
        ))

    def test_gemini_api_uploads_video_and_sends_its_uri(self):
        calls = self.clip()
        env = {"AUDYSSEY_PLANNER_API": "gemini", "AUDYSSEY_PLANNER_INPUT": "video",
               "AUDYSSEY_PLANNER_FPS": "3", "AUDYSSEY_PLANNER_VIDEO_AUDIO": "true"}
        with self.gemini(self.respond_gemini), patch.dict(os.environ, env), patch("time.sleep"):
            self.responses = ["broken", json.dumps({"sources": [self.source()]})]
            result = real.plan(self.video, self.audio, 2, [])
        self.assertEqual([p.name for p in result], ["person"])
        self.assertEqual(calls, [True])
        # One upload serves both attempts, is polled until active and deleted afterwards.
        self.assertEqual(self.uploaded, [b"clip-bytes"])
        self.assertEqual(self.uploads[0]["x-goog-upload-header-content-type"], "video/mp4")
        # The upload session URL is pre-authorized; every API call carries the key.
        self.assertTrue(all(key == "fake-key" for _, u, key in self.gemini_calls if "session-1" not in u))
        self.assertEqual([m for m, u, _ in self.gemini_calls if u.endswith("/files/abc")], ["GET", "DELETE"])
        first, second = self.requests
        self.assertTrue(first["url"].endswith("/models/fake-model:generateContent"))
        label, video, text = first["contents"][0]["parts"]
        self.assertEqual(label, {"text": "Video from 0 to 2 seconds"})
        self.assertEqual(video, {
            "fileData": {"mime_type": "video/mp4", "file_uri": "https://gemini.test/v1beta/files/abc"},
            "videoMetadata": {"fps": 3.0},
        })
        self.assertIn("Video duration: 2 seconds", text["text"])
        self.assertIn("audio track", first["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(first["generationConfig"], {"responseMimeType": "application/json"})
        self.assertEqual(second["contents"][0]["parts"][-1], {"text": "Return valid JSON matching the schema."})

    def test_gemini_api_error_masks_key(self):
        self.clip()
        env = {"AUDYSSEY_PLANNER_API": "gemini", "AUDYSSEY_PLANNER_INPUT": "video"}
        def bad(request):
            return httpx.Response(400, json={"error": {"code": 400, "message": "bad key fake-key"}})

        with self.gemini(bad), patch.dict(os.environ, env):
            with self.assertRaisesRegex(RuntimeError, "400") as caught:
                real.plan(self.video, self.audio, 2, [])
        self.assertNotIn("fake-key", str(caught.exception))
        self.assertIn("***", str(caught.exception))

    def test_openrouter_sends_video_without_vllm_fields(self):
        calls = self.clip()
        env = {"AUDYSSEY_PLANNER_API": "openrouter", "AUDYSSEY_PLANNER_INPUT": "video",
               "AUDYSSEY_PLANNER_VIDEO_AUDIO": "true"}
        with patch.dict(os.environ, env):
            self.plan([self.source()])
        request = self.requests[0]
        parts = request["messages"][1]["content"]
        self.assertEqual([p["type"] for p in parts], ["text", "text", "video_url"])
        self.assertNotIn("media_io_kwargs", request)
        self.assertNotIn("mm_processor_kwargs", request)
        self.assertEqual(calls, [True])
        self.assertIn("audio track", request["messages"][0]["content"])

    def visible(self, **updates):
        hint = {"time": 1, "box": [0.1, 0.1, 0.5, 0.5], "description": "person"}
        return SourcePlan(**self.source(visual_hint=hint, **updates))

    def test_validate_checks_each_source_in_its_spans(self):
        from audyssey.tools.planning import planning_scope

        plans = [
            self.visible(kind="sfx", spans=[{"start": 0.5, "end": 1.0}, {"start": 1.5, "end": 2.0}]),
            self.visible(name="dog", kind="sfx", description="a dog barking"),
        ]
        self.responses = [json.dumps({"status": "unsupported", "evidence": "none", "reason": "no person here"}),
                          json.dumps({"status": "supported", "evidence": "visual", "reason": "dog visible"})]
        with planning_scope("generate", False), patch.dict(os.environ, AUDYSSEY_VALIDATOR_CONTEXT_S="0"):
            issues = real.validate_plan(self.video, self.audio, plans)
        self.assertEqual(issues, [PlanIssue(source_name="person", kind="not_found",
                                            message="person: no person here")])
        first, second = self.requests
        text = "\n".join(p["text"] for p in first["messages"][1]["content"] if p["type"] == "text")
        self.assertIn('"name": "person"', text)
        self.assertIn('"target_intervals": [[0.5, 1.0], [1.5, 2.0]]', text)
        self.assertIn("Frame at 0.25 seconds", text)
        self.assertIn("scene-appropriate", first["messages"][0]["content"])
        # One frame per 0.5 s span at 1 fps; no spans means the whole video.
        windows = [(call.args[1], call.args[3], call.args[4]) for call in self.frames.call_args_list]
        self.assertEqual(windows, [(1, 0.5, 1.0), (1, 1.5, 2.0), (2, 0, 2.0)])
        self.assertIn('"target_intervals": [[0.0, 2.0]]', second["messages"][1]["content"][0]["text"])

    def test_separation_music_and_ambience_pass_without_audio(self):
        unseen = [SourcePlan(**self.source(name="wind", kind="ambience")),
                  SourcePlan(**self.source(name="score", kind="music"))]
        issues = real.validate_plan(self.video, self.audio, unseen)
        self.assertEqual([(i.source_name, i.kind) for i in issues],
                         [("wind", "not_validated"), ("score", "not_validated")])
        self.assertEqual(self.requests, [])

    def test_validate_hears_video_clips_with_audio(self):
        calls = self.clip(windows=True)
        env = {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true",
               "AUDYSSEY_VALIDATOR_FPS": "4", "AUDYSSEY_VALIDATOR_CONTEXT_S": "0"}
        offscreen = SourcePlan(**self.source(name="wind", kind="ambience",
                                             spans=[{"start": 0, "end": 1}, {"start": 1.5, "end": 2}]))
        self.responses = [json.dumps({"status": "supported", "evidence": "audio"})]
        with patch.dict(os.environ, env):
            self.assertEqual(real.validate_plan(self.video, self.audio, [offscreen]), [])
        self.assertEqual(calls, [(True, 0, 1), (True, 1.5, 2)])
        request = self.requests[0]
        types = [p["type"] for p in request["messages"][1]["content"]]
        self.assertEqual(types, ["text", "text", "video_url", "text", "video_url"])
        self.assertEqual(request["media_io_kwargs"], {"video": {"fps": 4.0, "num_frames": -1}})
        self.assertEqual(request["mm_processor_kwargs"], {"use_audio_in_video": True})
        self.assertIn("actually audible", request["messages"][0]["content"])
        self.assertNotIn("cannot hear", request["messages"][0]["content"])

    def test_validator_uses_its_own_model(self):
        env = {"AUDYSSEY_VALIDATOR_MODEL": "validator-model",
               "AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true"}
        self.clip()
        self.responses = [json.dumps({"status": "supported", "evidence": "audio"})]
        with patch.dict(os.environ, env):
            real.validate_plan(self.video, self.audio, [self.visible()])
            self.plan([self.source()])
        self.assertEqual([r["model"] for r in self.requests], ["validator-model", "fake-model"])

    def test_validate_bad_json_reports_each_schema_failure(self):
        for bad in ["bad", '{}', '{"present": "maybe"}', '[]']:
            with self.subTest(bad=bad):
                self.requests.clear()
                self.responses = [bad, bad]
                with patch.dict(os.environ, {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true"}):
                    self.clip()
                    issues = real.validate_plan(self.video, self.audio, [self.visible()])
                    self.assertEqual(issues[0].kind, "validation_error")
                self.assertEqual(len(self.requests), 2)

    def test_empty_plan_is_distinct_from_malformed_sources(self):
        self.assertEqual(self.plan([]), [])
        with self.assertRaisesRegex(RuntimeError, "no valid sources"):
            self.plan([{"kind": "invalid"}])

    def test_planning_purpose_and_audio_availability_reach_english_prompts(self):
        from audyssey.tools.planning import planning_scope

        calls = self.clip()
        env = {"AUDYSSEY_PLANNER_INPUT": "video", "AUDYSSEY_PLANNER_VIDEO_AUDIO": "true"}
        with patch.dict(os.environ, env):
            for purpose, available in [("separate", True), ("generate", False)]:
                with planning_scope(purpose, available):
                    self.plan([self.source()])
        separate, generate = self.requests
        self.assertIn("actually audible", separate["messages"][0]["content"])
        self.assertIn("Do not invent", separate["messages"][0]["content"])
        self.assertIn('"purpose": "separate"', separate["messages"][1]["content"][0]["text"])
        self.assertIn("scene-appropriate", generate["messages"][0]["content"])
        self.assertIn('"audio_available": false', generate["messages"][1]["content"][0]["text"])
        self.assertNotIn("audio track", generate["messages"][0]["content"])
        self.assertEqual(calls, [True, False])
        self.assertNotIn("mm_processor_kwargs", generate)
        for request in self.requests:
            self.assertFalse(any("\uac00" <= c <= "\ud7a3" for c in request["messages"][0]["content"]))

    def test_visual_evidence_does_not_approve_separation(self):
        self.clip()
        with patch.dict(os.environ, {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true"}):
            self.responses = [json.dumps({"status": "supported", "evidence": "visual", "reason": "a dog is visible"})]
            issues = real.validate_plan(self.video, self.audio, [self.visible()])
        self.assertEqual(issues[0].kind, "validation_uncertain")

    def test_silent_generation_can_be_supported_by_visual_evidence(self):
        from audyssey.tools.planning import planning_scope

        self.responses = [json.dumps({"status": "supported", "evidence": "visual", "reason": "the ball hits the floor"})]
        with planning_scope("generate", False):
            issues = real.validate_plan(self.video, self.audio, [self.visible(kind="sfx")])
        self.assertEqual(issues, [])
        self.assertIn("scene-appropriate", self.requests[0]["messages"][0]["content"])

    def test_separation_visual_mode_validates_visible_producer(self):
        self.responses = [json.dumps({"status": "supported", "evidence": "visual", "reason": "a person talks on screen"})]
        issues = real.validate_plan(self.video, self.audio, [self.visible()])
        self.assertEqual(issues, [])
        system = self.requests[0]["messages"][0]["content"]
        self.assertIn("producer", system)
        self.assertIn("cannot hear", system)

    def test_separation_visual_mode_passes_music_ambience_and_offscreen_without_call(self):
        plans = [SourcePlan(**self.source(name="wind", kind="ambience")),
                 SourcePlan(**self.source(name="score", kind="music")),
                 SourcePlan(**self.source(name="narrator"))]  # no visual_hint: offscreen
        issues = real.validate_plan(self.video, self.audio, plans)
        self.assertEqual([(i.source_name, i.kind) for i in issues],
                         [("wind", "not_validated"), ("score", "not_validated"), ("narrator", "not_validated")])
        self.assertEqual(self.requests, [])

    def test_oversize_audio_falls_back_to_visual_validation(self):
        self.responses = [json.dumps({"status": "supported", "evidence": "visual", "reason": "person visible"})]
        env = {"AUDYSSEY_VALIDATOR_AUDIO": "true", "AUDYSSEY_VALIDATOR_CONTEXT_S": "0"}
        with patch.dict(os.environ, env), patch.object(real, "_MAX_INLINE_B64", 10):
            self.assertEqual(real.validate_plan(self.video, self.audio, [self.visible()]), [])
        types = [p["type"] for p in self.requests[0]["messages"][1]["content"]]
        self.assertNotIn("input_audio", types)
        self.assertIn("cannot hear", self.requests[0]["messages"][0]["content"])

    def test_oversize_audio_music_is_not_validated_without_call(self):
        env = {"AUDYSSEY_VALIDATOR_AUDIO": "true"}
        with patch.dict(os.environ, env), patch.object(real, "_MAX_INLINE_B64", 10):
            issues = real.validate_plan(self.video, self.audio, [SourcePlan(**self.source(name="score", kind="music"))])
        self.assertEqual([(i.source_name, i.kind) for i in issues], [("score", "not_validated")])
        self.assertEqual(self.requests, [])

    def test_separation_without_soundtrack_is_unavailable(self):
        from audyssey.tools.planning import planning_scope

        with planning_scope("separate", False):
            issues = real.validate_plan(self.video, self.audio, [self.visible()])
        self.assertEqual(issues[0].kind, "validation_unavailable")
        self.assertEqual(self.requests, [])

    def test_validator_audio_false_strips_audio_from_clips(self):
        calls = self.clip()
        self.responses = [json.dumps({"status": "supported", "evidence": "visual", "reason": "person visible"})]
        env = {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true",
               "AUDYSSEY_VALIDATOR_AUDIO": "false"}
        with patch.dict(os.environ, env):
            self.assertEqual(real.validate_plan(self.video, self.audio, [self.visible()]), [])
        self.assertEqual(calls, [False])
        self.assertNotIn("mm_processor_kwargs", self.requests[0])

    def test_validator_audio_true_sends_wav_even_with_frames_input(self):
        self.responses = [json.dumps({"status": "supported", "evidence": "audio", "reason": "speech heard"})]
        with patch.dict(os.environ, {"AUDYSSEY_VALIDATOR_AUDIO": "true"}):
            self.assertEqual(real.validate_plan(self.video, self.audio, [self.visible()]), [])
        types = [p["type"] for p in self.requests[0]["messages"][1]["content"]]
        self.assertIn("input_audio", types)
        self.assertNotIn("image_url", types)

    def test_bad_validator_json_is_not_an_approval(self):
        self.clip()
        with patch.dict(os.environ, {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true"}):
            self.responses = ["broken", "broken"]
            issues = real.validate_plan(self.video, self.audio, [self.visible()])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(issues[0].kind, "validation_error")

    def test_context_clips_are_merged_and_target_times_remain_explicit(self):
        calls = self.clip(windows=True)
        plan = self.visible(spans=[{"start": 0.5, "end": 0.6}, {"start": 1.0, "end": 1.1}])
        self.responses = [json.dumps({"status": "supported", "evidence": "audio", "reason": "speech in both target intervals"})]
        env = {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true", "AUDYSSEY_VALIDATOR_CONTEXT_S": "0.5"}
        with patch.dict(os.environ, env):
            self.assertEqual(real.validate_plan(self.video, self.audio, [plan]), [])
        self.assertEqual(calls, [(True, 0.0, 1.6)])
        text = self.requests[0]["messages"][1]["content"][0]["text"]
        payload = json.loads(text)
        self.assertEqual(payload["target_intervals"], [[0.5, 0.6], [1.0, 1.1]])
        self.assertEqual(payload["context_intervals"], [[0.0, 1.6]])
        self.assertIn("original_time", self.requests[0]["messages"][0]["content"])

    def test_explicit_uncertainty_remains_an_issue(self):
        self.clip()
        self.responses = [json.dumps({"status": "uncertain", "evidence": "audio", "reason": "speech is masked by music"})]
        with patch.dict(os.environ, {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true"}):
            issues = real.validate_plan(self.video, self.audio, [self.visible()])
        self.assertEqual(issues[0].kind, "validation_uncertain")

    def test_out_of_bounds_target_is_rejected_before_model_call(self):
        plan = self.visible(spans=[{"start": 1.8, "end": 3.0}])
        with patch.dict(os.environ, {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true"}):
            issues = real.validate_plan(self.video, self.audio, [plan])
        self.assertEqual(issues[0].kind, "span_out_of_range")
        self.assertEqual(self.requests, [])

    def test_digital_silence_in_target_is_rejected_before_model_call(self):
        import numpy as np
        from audyssey.media import write_wav

        audio = np.zeros((96000, 2), dtype=np.float32)
        audio[60000:70000] = 0.2
        write_wav(self.audio, audio)
        plan = self.visible(spans=[{"start": 0.6, "end": 0.8}])
        with patch.dict(os.environ, {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true"}):
            issues = real.validate_plan(self.video, self.audio, [plan])
        self.assertEqual(issues[0].kind, "not_found")
        self.assertIn("silent", issues[0].message)
        self.assertEqual(self.requests, [])

    def test_audio_only_validator_sends_pcm_wav_without_video_or_vllm_flags(self):
        import io
        import wave
        import numpy as np
        from audyssey.media import write_wav
        tone = 0.2 * np.sin(2 * np.pi * 440 * np.arange(96000) / 48000)
        write_wav(self.audio, np.column_stack((tone, -tone)))
        self.responses = [json.dumps({"status": "supported", "evidence": "audio"})]
        env = {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true",
               "AUDYSSEY_VALIDATOR_AUDIO_ONLY": "true", "AUDYSSEY_VALIDATOR_CONTEXT_S": "0"}
        with patch.dict(os.environ, env):
            self.assertEqual(real.validate_plan(self.video, self.audio, [self.visible()]), [])
        request = self.requests[0]
        parts = request["messages"][1]["content"]
        self.assertEqual([p["type"] for p in parts], ["text", "text", "input_audio"])
        payload = parts[-1]["input_audio"]
        self.assertEqual(payload["format"], "wav")
        with wave.open(io.BytesIO(base64.b64decode(payload["data"]))) as audio:
            self.assertEqual((audio.getframerate(), audio.getsampwidth(), audio.getnframes()), (16000, 2, 32000))
            self.assertEqual(audio.getnchannels(), 2)
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").reshape(-1, 2)
            self.assertGreater(np.max(np.abs(samples)), 0)
            np.testing.assert_array_equal(samples.sum(axis=1), 0)
        self.assertNotIn("media_io_kwargs", request)
        self.assertNotIn("mm_processor_kwargs", request)

    def test_native_gemini_audio_validation_sends_inline_wav_without_upload(self):
        self.responses = [json.dumps({"status": "supported", "evidence": "audio"})]
        env = {"AUDYSSEY_VALIDATOR_API": "gemini", "AUDYSSEY_VALIDATOR_INPUT": "video",
               "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true", "AUDYSSEY_VALIDATOR_AUDIO_ONLY": "true"}
        with self.gemini(self.respond_gemini), patch.dict(os.environ, env):
            self.assertEqual(real.validate_plan(self.video, self.audio, [self.visible()]), [])
        self.assertEqual(self.uploaded, [])
        parts = self.requests[0]["contents"][0]["parts"]
        audio = next(p["inlineData"] for p in parts if "inlineData" in p)
        self.assertEqual(audio.get("mime_type", audio.get("mimeType")), "audio/wav")
        self.assertTrue(base64.urlsafe_b64decode(audio["data"] + "==").startswith(b"RIFF"))

    def test_unavailable_audio_cannot_support_a_rejection_either(self):
        from audyssey.tools.planning import planning_scope

        self.responses = [json.dumps({"status": "unsupported", "evidence": "audio", "reason": "no sound"})]
        with planning_scope("generate", False):
            issues = real.validate_plan(self.video, self.audio, [self.visible(kind="sfx")])
        self.assertEqual(issues[0].kind, "validation_uncertain")

    def test_planner_traces_exclude_frames_and_preserve_usage(self):
        from langsmith import Client
        from langsmith.run_helpers import tracing_context
        from unittest.mock import Mock
        from audyssey.settings import Settings
        from audyssey.tools import load_tools

        for nested in (False, True):
            with self.subTest(nested=nested):
                trace_client = Mock(spec=Client)
                self.responses = [json.dumps({"sources": [self.source()]})]
                planner = load_tools(Settings(planner="real")).plan if nested else real.plan
                with tracing_context(enabled=True, client=trace_client):
                    planner(self.video, self.audio, 2, [])
                recorded = str(trace_client.mock_calls)
                encoded = base64.b64encode(self.image.read_bytes()).decode()
                self.assertNotIn(encoded, recorded)
                llm_runs = [call.kwargs for call in trace_client.create_run.call_args_list
                            if call.kwargs["run_type"] == "llm"]
                self.assertEqual(len(llm_runs), 1)
                if nested:
                    tool_run = next(call.kwargs for call in trace_client.create_run.call_args_list
                                    if call.kwargs["run_type"] == "tool")
                    self.assertEqual(llm_runs[0]["parent_run_id"], tool_run["id"])
                else:
                    self.assertIsNone(llm_runs[0].get("parent_run_id"))
                outputs = [call.kwargs.get("outputs", {})
                           for call in trace_client.update_run.call_args_list]
                self.assertTrue(any(output.get("usage_metadata") == {
                    "input_tokens": 3, "output_tokens": 5, "total_tokens": 8,
                } for output in outputs), outputs)
