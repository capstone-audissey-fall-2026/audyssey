import os
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from audyssey.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        settings = Settings()
        self.assertEqual(
            (settings.planner, settings.separator, settings.filter),
            ("stub", "stub", "stub"),
        )
        self.assertEqual(
            (
                settings.max_plan_rounds,
                settings.max_separation_retries,
                settings.max_duration_s,
            ),
            (2, 2, 30),
        )

    def test_router_defaults_to_stub_and_reads_env(self):
        self.assertEqual(Settings().router, "stub")
        with patch.dict(os.environ, AUDYSSEY_ROUTER="real"):
            self.assertEqual(Settings().router, "real")

    def test_hybrid_router_settings(self):
        with self.assertRaisesRegex(ValidationError, "AUDYSSEY_ROUTER_DECISION_URL"):
            Settings(router="hybrid")
        Settings(router="hybrid", router_decision_url="http://d")
        settings = Settings()
        self.assertEqual(
            (settings.router_decision_url, settings.router_hybrid_escape,
             settings.router_decision_model),
            ("", False, "h2o-lightning-4b"),
        )
        env = {"AUDYSSEY_ROUTER": "hybrid", "AUDYSSEY_ROUTER_DECISION_URL": "http://d",
               "AUDYSSEY_ROUTER_HYBRID_ESCAPE": "true", "AUDYSSEY_ROUTER_DECISION_MODEL": "x"}
        with patch.dict(os.environ, env):
            settings = Settings()
        self.assertEqual(
            (settings.router, settings.router_hybrid_escape, settings.router_decision_model),
            ("hybrid", True, "x"),
        )

    def test_router_guard_defaults_off_and_reads_env(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(Settings().router_guard)
        with patch.dict(os.environ, {"AUDYSSEY_ROUTER_GUARD": "true"}, clear=True):
            self.assertTrue(Settings().router_guard)

    def test_router_reasoning_effort(self):
        self.assertIsNone(Settings().router_reasoning_effort)
        with patch.dict(os.environ, AUDYSSEY_ROUTER_REASONING_EFFORT="none"):
            self.assertEqual(Settings().router_reasoning_effort, "none")
        with patch.dict(os.environ, AUDYSSEY_ROUTER_REASONING_EFFORT="max"):
            with self.assertRaises(ValidationError):
                Settings()

    def test_env_override(self):
        with patch.dict(
            os.environ, AUDYSSEY_PLANNER="real", AUDYSSEY_MAX_PLAN_ROUNDS="3"
        ):
            settings = Settings()
        self.assertEqual((settings.planner, settings.max_plan_rounds), ("real", 3))

    def test_rejects_unknown_mode(self):
        with patch.dict(os.environ, AUDYSSEY_SEPARATOR="gpu"):
            with self.assertRaises(ValidationError):
                Settings()

    def test_remote_modes_and_urls_from_env(self):
        with patch.dict(os.environ, {
            "AUDYSSEY_SEPARATOR": "remote",
            "AUDYSSEY_SEPARATOR_URL": "http://gpu:8700",
            "AUDYSSEY_TOOL_TOKEN": "t",
            "AUDYSSEY_PLANNER_BASE_URL": "http://llm/v1",
            "AUDYSSEY_PLANNER_MODEL": "m",
        }, clear=True):
            settings = Settings()
        self.assertEqual(settings.separator, "remote")
        self.assertEqual(settings.separator_url, "http://gpu:8700")
        self.assertEqual(settings.tool_token, "t")
        self.assertEqual(settings.planner_base_url, "http://llm/v1")
        self.assertEqual(settings.planner_model, "m")
        self.assertEqual(settings.filter, "stub")
        self.assertEqual(settings.remote_timeout_s, 600)

    def test_remote_timeout_must_be_positive(self):
        with patch.dict(os.environ, AUDYSSEY_REMOTE_TIMEOUT_S="0"):
            with self.assertRaises(ValidationError):
                Settings()

    def test_sam_audio_settings_from_env(self):
        with patch.dict(os.environ, {
            "AUDYSSEY_SAM_AUDIO_DEVICE": "cpu",
            "AUDYSSEY_SAM_AUDIO_RERANKING_CANDIDATES": "3",
            "AUDYSSEY_SAM_AUDIO_PREDICT_SPANS": "true",
            "AUDYSSEY_JUDGE_PASS_THRESHOLD": "0.7",
        }, clear=True):
            settings = Settings()
        self.assertEqual(settings.sam_audio_device, "cpu")
        self.assertEqual(settings.sam_audio_reranking_candidates, 3)
        self.assertTrue(settings.sam_audio_predict_spans)
        self.assertEqual(settings.judge_pass_threshold, 0.7)
        with self.assertRaises(ValidationError):
            Settings(sam_audio_reranking_candidates=0)

    def test_grounding_defaults_and_environment(self):
        defaults = Settings()
        self.assertEqual((defaults.grounder, defaults.grounding_url, defaults.sam3_model, defaults.sam3_device),
                         ('stub', '', 'facebook/sam3.1', 'cuda'))
        with patch.dict(os.environ, AUDYSSEY_GROUNDER='remote', AUDYSSEY_GROUNDING_URL='http://grounding:8700', AUDYSSEY_SAM3_DEVICE='cpu', AUDYSSEY_SAM3_MODEL='local/model'):
            settings = Settings()
        self.assertEqual((settings.grounder, settings.grounding_url, settings.sam3_device, settings.sam3_model),
                         ('remote', 'http://grounding:8700', 'cpu', 'local/model'))
        with self.assertRaises(ValidationError):
            Settings(grounder='unknown')

    def test_planner_max_frames_bounds_and_env(self):
        self.assertEqual(Settings().planner_max_frames, 32)
        with patch.dict(os.environ, AUDYSSEY_PLANNER_MAX_FRAMES="8"):
            self.assertEqual(Settings().planner_max_frames, 8)
        for count in (0, 257):
            with self.assertRaises(ValidationError):
                Settings(planner_max_frames=count)

    def test_validator_context_bounds_and_environment(self):
        self.assertEqual(Settings().validator_context_s, 0.5)
        self.assertTrue(Settings().validator_audio_only)
        with patch.dict(os.environ, AUDYSSEY_VALIDATOR_AUDIO_ONLY="false"):
            self.assertFalse(Settings().validator_audio_only)
        with patch.dict(os.environ, AUDYSSEY_VALIDATOR_CONTEXT_S="0.25"):
            self.assertEqual(Settings().validator_context_s, 0.25)
        for value in (-0.1, 5.1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Settings(validator_context_s=value)

    def test_validator_endpoint_falls_back_to_planner(self):
        settings = Settings(planner_base_url="http://planner/v1", planner_model="p",
                            planner_api_key="k", planner_fps=2)
        self.assertEqual(settings.validator_endpoint(), settings.planner_endpoint())
        env = {"AUDYSSEY_VALIDATOR_BASE_URL": "http://validator/v1", "AUDYSSEY_VALIDATOR_MODEL": "v",
               "AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true"}
        with patch.dict(os.environ, env):
            settings = Settings(planner_base_url="http://planner/v1", planner_model="p",
                                planner_api_key="k", planner_fps=2)
        validator = settings.validator_endpoint()
        self.assertEqual((validator.base_url, validator.model, validator.input, validator.video_audio),
                         ("http://validator/v1", "v", "video", True))
        self.assertEqual((validator.api_key, validator.fps, validator.api), ("k", 2, "openai"))
        self.assertEqual(settings.planner_endpoint().model, "p")
        with self.assertRaises(ValidationError):
            Settings(validator_api="gemini")
        Settings(validator_api="gemini", validator_input="video")

    def test_router_endpoint_falls_back_to_planner(self):
        planner = dict(planner_base_url="http://planner/v1", planner_model="p", planner_api_key="k")
        settings = Settings(**planner)
        self.assertEqual(settings.router_endpoint(), settings.planner_endpoint())
        settings = Settings(router_model="r", router_api="openrouter", **planner)
        router = settings.router_endpoint()
        self.assertEqual((router.model, router.api), ("r", "openrouter"))
        self.assertEqual((router.base_url, router.api_key), ("http://planner/v1", "k"))
        self.assertEqual(settings.planner_endpoint().model, "p")
        settings = Settings(router_base_url="http://router/v1", router_api_key="router-secret-key", **planner)
        router = settings.router_endpoint()
        self.assertEqual((router.base_url, router.api_key, router.model), ("http://router/v1", "router-secret-key", "p"))
        self.assertNotIn("router-secret-key", repr(settings))

    def test_real_router_rejects_gemini(self):
        with self.assertRaisesRegex(ValidationError, "AUDYSSEY_ROUTER_API must be openai or openrouter"):
            Settings(router="real", router_api="gemini", planner_input="video")
        Settings(router="stub", router_api="gemini", planner_input="video")
        Settings(router="real", router_api="openrouter")

    def test_planner_input_settings(self):
        settings = Settings()
        self.assertEqual(
            (settings.planner_api, settings.planner_input, settings.planner_fps, settings.planner_video_audio),
            ("openai", "frames", 1.0, False),
        )
        env = {"AUDYSSEY_PLANNER_API": "gemini", "AUDYSSEY_PLANNER_INPUT": "video",
               "AUDYSSEY_PLANNER_FPS": "2.5", "AUDYSSEY_PLANNER_VIDEO_AUDIO": "true"}
        with patch.dict(os.environ, env):
            settings = Settings()
        self.assertEqual(
            (settings.planner_api, settings.planner_input, settings.planner_fps, settings.planner_video_audio),
            ("gemini", "video", 2.5, True),
        )
        for bad in ({"planner_fps": 0}, {"planner_fps": 31}, {"planner_api": "x"}, {"planner_input": "x"},
                    {"planner_api": "gemini", "planner_input": "frames"}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                Settings(**bad)

    def test_generation_settings_from_env(self):
        values = {"GENERATOR": "remote", "GENERATOR_URL": "http://generation:8700", "GEN_BASE_MODEL": "base", "GEN_MODEL": "private/ft", "GEN_GENERATOR_FILE": "g.pth", "GEN_ENCODER_FILE": "e.pt", "GEN_DEVICE": "cpu", "GEN_STEPS": "5", "GEN_CFG": "3.5", "GEN_SEED": "17", "GEN_SINGLE_MAX_S": "9", "GEN_WINDOW_S": "7", "MAX_GENERATION_RETRIES": "0", "GENERATION_MARGIN_THRESHOLD": "0.2"}
        with patch.dict(os.environ, {"AUDYSSEY_" + k: v for k, v in values.items()}, clear=True):
            settings = Settings()
        for name, expected in values.items():
            self.assertEqual(str(getattr(settings, name.lower())), str(float(expected)) if name in {"GEN_CFG", "GEN_SINGLE_MAX_S", "GEN_WINDOW_S", "GENERATION_MARGIN_THRESHOLD"} else expected)
        with self.assertRaises(ValidationError):
            Settings(max_generation_retries=-1)
        with self.assertRaises(ValidationError):
            Settings(generator="unknown")
