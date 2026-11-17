import tempfile
import unittest
from pathlib import Path

from audyssey import trace
from audyssey.contracts import SourcePlan
from audyssey.settings import Settings


class LaneTests(unittest.TestCase):
    def test_openrouter_is_named_for_its_provider(self):
        for base_url in (
            "https://openrouter.ai/api/v1",
            "https://eu.openrouter.ai:443/api/v1",
        ):
            with self.subTest(base_url=base_url):
                settings = Settings(
                    planner="real",
                    planner_base_url=base_url,
                    planner_model="google/gemini-2.5-flash",
                )
                lane = next(lane for lane in trace.lanes(settings) if "plan" in lane["steps"])
                self.assertEqual(lane["name"], "OpenRouter")

    def test_lanes_group_steps_by_server(self):
        settings = Settings(
            planner="real", planner_api="gemini", planner_input="video", planner_model="gemini-x",
            planner_base_url="https://gemini", validator_api="openai", validator_input="video",
            validator_base_url="http://vllm:8000/v1", validator_model="Qwen/VL",
            separator="remote", separator_url="http://pod:8700", filter="remote", filter_url="http://pod:8700",
            generator="real", gen_model="private/gen",
        )
        lanes = {lane["id"]: lane for lane in trace.lanes(settings)}
        self.assertEqual(lanes["gemini"]["steps"], ["plan"])
        self.assertEqual(lanes["gemini"]["models"], ["gemini-x"])
        self.assertEqual(lanes["llm:vllm:8000"]["steps"], ["validate_plan"])
        # One endpoint serving two tools is one server.
        self.assertEqual(lanes["tool:pod:8700"]["steps"], ["separate", "judge"])
        self.assertEqual(lanes["app"]["steps"], ["preprocess", "generate", "score", "residual", "render"])
        self.assertIn("private/gen", lanes["app"]["models"])
        self.assertNotIn("ground", [s for lane in lanes.values() for s in lane["steps"]])

    def test_planner_and_validator_share_a_lane_when_they_share_a_model(self):
        settings = Settings(planner="real", planner_base_url="http://vllm:8000/v1", planner_model="m")
        lane = next(x for x in trace.lanes(settings) if x["id"].startswith("llm:"))
        self.assertEqual(lane["steps"], ["plan", "validate_plan"])


class CallTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def test_call_writes_inputs_outputs_and_errors(self):
        audio = self.root / "a.wav"
        audio.write_bytes(b"wav")
        trace.set_step("separate:s1")
        with trace.call(self.root, "separate", "App server", {"audio": trace.describe(audio, self.root)}) as record:
            record.output = trace.describe(audio, self.root, record)
            record.requests.append({"raw": "{}"})
        with self.assertRaises(ValueError), trace.call(self.root, "judge", "App server", {}):
            raise ValueError("boom")
        first, second = trace.read(self.root)
        self.assertEqual(first["step"], "separate:s1")
        self.assertEqual(first["inputs"], {"audio": {"file": "a.wav"}})
        self.assertEqual(first["output"], {"file": f"trace/{first['id']}/a.wav"})
        self.assertEqual((self.root / first["output"]["file"]).read_bytes(), b"wav")
        self.assertEqual(first["requests"], [{"raw": "{}"}])
        self.assertEqual(second["error"], "boom")
        self.assertIsNone(trace.current())

    def test_describe_keeps_models_and_outside_paths(self):
        plan = SourcePlan(name="dog", kind="sfx", description="bark")
        self.assertEqual(trace.describe([plan], self.root)[0]["name"], "dog")
        outside = Path("/elsewhere.wav")
        self.assertEqual(trace.describe(outside, self.root), str(outside))
        self.assertEqual(trace.describe(self.root / "missing.wav", self.root), str(self.root / "missing.wav"))
