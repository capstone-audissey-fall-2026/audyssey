import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from scipy.io import wavfile

from audyssey.contracts import FilterResult, SourcePlan, Span
from audyssey.media import write_wav
from audyssey.settings import Settings
from audyssey.tools import judge_verdict, load_tools
from audyssey.tools.filtering import agent as filtering_agent
from audyssey.tools.filtering.stem_agent import StemFilterAgent, load_config
from audyssey.tools.filtering.stem_agent.audio import Clip
from audyssey.tools.filtering.stem_agent.backend import (
    OpenAICompatBackend,
    p_yes_from_top_logprobs,
)
from audyssey.tools.filtering.stem_agent.config import BackendConfig
from tests.stem_agent_fakes import MockBackend


def tone(seconds: float = 4.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(48000 * seconds)) / 48000
    return (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32).reshape(-1, 1)


class StemAgentJudgeTests(unittest.TestCase):
    """The fake judge answers from tags in the track file name: absent, mixed, missing, unsure."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.mono = write_wav(self.dir / "mono.wav", tone())
        self.plan = SourcePlan(name="dog", kind="sfx", description="dog barking")
        self.fake = MockBackend()
        agent = StemFilterAgent(load_config(), self.fake)
        patcher = mock.patch.object(filtering_agent, "_agent", return_value=agent)
        patcher.start()
        self.addCleanup(patcher.stop)

    def judge(self, name: str, audio: np.ndarray | None = None, plan=None):
        track = write_wav(self.dir / name, tone() if audio is None else audio)
        return filtering_agent.judge(self.mono, track, plan or self.plan)

    def test_clean_track_is_accepted_with_stage_scores(self):
        result = self.judge("clean.wav")
        self.assertTrue(result.passed)
        self.assertEqual(result.scores["overall"], 1.0)
        for key in ("p_present", "p_other", "p_missing", "recall", "precision"):
            self.assertIn(key, result.scores)
        self.assertAlmostEqual(result.scores["recall"], 1 - result.scores["p_missing"])
        self.assertAlmostEqual(result.scores["precision"], 1 - result.scores["p_other"])
        self.assertIsNone(result.suggestion)

    def test_leaked_sound_is_rejected_at_purity_without_suggestion(self):
        result = self.judge("track_mixed.wav")
        self.assertFalse(result.passed)
        self.assertEqual(result.scores["overall"], 0.0)
        self.assertTrue(result.reason.startswith("agent REJECT at purity"))
        self.assertIn("crowd noise", result.reason)
        self.assertNotIn("p_missing", result.scores)  # early exit: completeness not run
        self.assertIsNone(result.suggestion)

    def test_missing_part_suggests_the_gap_as_a_span_anchor(self):
        plan = self.plan.model_copy(update={"spans": [Span(start=0.0, end=1.0)]})
        result = self.judge("track_missing.wav", plan=plan)
        self.assertTrue(result.reason.startswith("agent REJECT at completeness"))
        self.assertIsNotNone(result.suggestion)
        assert result.suggestion is not None
        self.assertEqual(
            [(s.start, s.end) for s in result.suggestion.spans],
            [(0.0, 1.0), (2.0, 3.0)],
        )
        self.assertEqual(result.suggestion.description, plan.description)

    def test_absent_target_is_rejected_at_presence(self):
        result = self.judge("track_absent.wav")
        self.assertTrue(result.reason.startswith("agent REJECT at presence"))

    def test_digital_silence_fails_without_asking_the_model(self):
        result = self.judge("silent.wav", np.zeros((48000, 1), dtype=np.float32))
        self.assertFalse(result.passed)
        self.assertIn("digitally silent", result.reason)
        self.assertEqual(self.fake.calls, 0)

    def test_unsure_is_hold_and_fails_the_default_threshold(self):
        # The fake answers 0.45 to every question; these bands make that PASS for presence and
        # completeness and UNSURE for purity, so the agent returns HOLD.
        cfg = load_config(
            overrides={
                "presence": {"pass_at": 0.4, "fail_at": 0.3},
                "purity": {"pass_at": 0.3, "fail_at": 0.5},
            }
        )
        agent = StemFilterAgent(cfg, MockBackend())
        with mock.patch.object(filtering_agent, "_agent", return_value=agent):
            result = self.judge("track_unsure.wav")
        self.assertEqual(result.scores["overall"], 0.4)
        self.assertTrue(result.reason.startswith("agent HOLD"))
        self.assertFalse(judge_verdict(result, 0.5).passed)
        # A team that wants unsure stems kept can lower the app threshold.
        self.assertTrue(judge_verdict(result, 0.4).passed)


class StemAgentWiringTests(unittest.TestCase):
    def test_agent_mode_requires_url(self):
        with self.assertRaisesRegex(ValueError, "AUDYSSEY_STEM_AGENT_URL"):
            load_tools(Settings(filter="agent", stem_agent_url=" "))

    def test_load_tools_keeps_the_agent_reason_after_the_app_verdict(self):
        tool_result = FilterResult(
            passed=False, scores={"overall": 0.0}, reason="agent REJECT at purity: leak"
        )
        with mock.patch.object(filtering_agent, "judge", return_value=tool_result):
            tools = load_tools(
                Settings(filter="agent", stem_agent_url="http://judge/v1")
            )
            result = tools.judge(
                Path("m.wav"),
                Path("t.wav"),
                SourcePlan(name="a", kind="sfx", description="a"),
            )
        self.assertFalse(result.passed)
        self.assertEqual(
            result.reason, "judge overall 0.00 < 0.5: agent REJECT at purity: leak"
        )

    def test_sam_judge_reason_is_not_repeated(self):
        tool = FilterResult(
            passed=False, scores={"overall": 0.2}, reason="judge overall 0.20 < 0.6"
        )
        self.assertEqual(judge_verdict(tool, 0.5).reason, "judge overall 0.20 < 0.5")

    def test_settings_feed_the_agent_config(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"purity": {"pass_at": 0.36}}, fh)
        settings = Settings(
            filter="agent",
            stem_agent_url="http://judge/v1",
            stem_agent_model="m",
            stem_agent_timeout_s=30,
            stem_agent_config=fh.name,
        )
        cfg = filtering_agent.agent_config(settings)
        self.assertEqual(
            (cfg.backend.base_url, cfg.backend.model, cfg.backend.timeout_s),
            ("http://judge/v1", "m", 30),
        )
        self.assertEqual(cfg.purity.pass_at, 0.36)
        self.assertEqual(cfg.presence.pass_at, load_config().presence.pass_at)

    def test_api_key_is_not_in_settings_repr(self):
        self.assertNotIn("secret-key", repr(Settings(stem_agent_api_key="secret-key")))


class StemAgentBackendTests(unittest.TestCase):
    def test_wav_bytes_are_16_bit_pcm_at_the_clip_rate(self):
        clip = Clip(np.linspace(-1.5, 1.5, 1600).astype(np.float32), 16000, "x")
        rate, data = wavfile.read(io.BytesIO(clip.to_wav_bytes()))
        self.assertEqual(
            (rate, data.dtype, len(data)), (16000, np.dtype("int16"), 1600)
        )
        self.assertEqual((int(data.min()), int(data.max())), (-32767, 32767))

    def test_audio_is_sent_as_audio_url_data_uri(self):
        backend = OpenAICompatBackend(BackendConfig(base_url="http://judge/v1"))
        content = backend._content([Clip(np.zeros(160, np.float32), 16000), "question"])
        self.assertEqual(content[0]["type"], "audio_url")
        self.assertTrue(
            content[0]["audio_url"]["url"].startswith("data:audio/wav;base64,")
        )
        self.assertEqual(content[1], {"type": "text", "text": "question"})

    def test_yes_probability_from_logprobs(self):
        p = p_yes_from_top_logprobs(
            [("YES", np.log(0.6)), ("No", np.log(0.2)), ("Maybe", 0.0)]
        )
        self.assertAlmostEqual(p or 0, 0.75)
        self.assertIsNone(p_yes_from_top_logprobs([("Maybe", 0.0)]))


if __name__ == "__main__":
    unittest.main()
