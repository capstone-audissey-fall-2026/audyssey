import tempfile
import unittest
from pathlib import Path

from audyssey import graph
from audyssey.contracts import FilterResult
from audyssey.settings import Settings
from audyssey.store import JobStore
from audyssey.tools import generation_verdict, judge_verdict, load_tools
from tests.audyssey_media import make_video


class VerdictTests(unittest.TestCase):
    def test_judge_compares_overall_with_the_app_threshold(self):
        tool = FilterResult(passed=True, scores={"overall": 4.45})
        self.assertTrue(judge_verdict(tool, 0.5).passed)
        failed = judge_verdict(tool, 5.1)
        self.assertFalse(failed.passed)
        self.assertEqual(failed.reason, "judge overall 4.45 < 5.1")
        self.assertEqual(failed.scores, {"overall": 4.45})

    def test_judge_without_overall_fails_and_keeps_the_tool_reason(self):
        tool = FilterResult(passed=True, reason="leakage")
        self.assertEqual(judge_verdict(tool, 0.5).model_dump()["passed"], False)
        self.assertEqual(judge_verdict(tool, 0.5).reason, "leakage")

    def test_generation_margin_and_sibling_cases(self):
        close = FilterResult(passed=True, scores={"text_correct": 1, "text_margin": 0.09})
        self.assertTrue(generation_verdict(close, 0.0).passed)
        below = generation_verdict(close, 10)
        self.assertFalse(below.passed)
        self.assertEqual(below.reason, "text margin 0.090 below threshold 10")
        wrong = FilterResult(
            passed=False,
            scores={"text_correct": 0, "text_margin": -0.04},
            reason="closer to sibling: rain",
        )
        self.assertEqual(generation_verdict(wrong, -1).reason, "closer to sibling: rain")
        self.assertFalse(generation_verdict(wrong, -1).passed)
        # Without siblings there is no margin; text_correct alone decides.
        alone = FilterResult(passed=True, scores={"text_correct": 1})
        self.assertTrue(generation_verdict(alone, 10).passed)


class AppThresholdRetryTests(unittest.TestCase):
    """The tool server says pass; a stricter app threshold must still retry."""

    def run_job(self, method, **thresholds):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        video = make_video(root / "clip.mp4", audio=method == "separate")
        settings = Settings(work_dir=root / "jobs", **thresholds)
        ctx = graph.Context(load_tools(settings), settings, JobStore(settings.work_dir))
        job, _ = ctx.store.create("clip.mp4", video.read_bytes())
        return graph.analyze(job, ctx, method=method), settings

    def test_separation_retries_until_the_app_threshold_or_max(self):
        # The stub judge scores 4.5 and passes it itself.
        job, settings = self.run_job("separate", judge_pass_threshold=4.95)
        self.assertEqual(job.state, "ready", job.error)
        maximum = settings.max_separation_retries + 1
        for source in job.sources:
            self.assertEqual(source.attempts, maximum)
            self.assertFalse(source.filter.passed)
            self.assertEqual(source.filter.reason, "judge overall 4.50 < 4.95")

    def test_generation_score_uses_the_app_threshold(self):
        from audyssey.tools.planning import stub as planning

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        video = make_video(root / "silent.mp4", audio=False)
        plan = planning.plan(video, Path("unused"), 3, [])[2]
        sibling = plan.model_copy(update={"name": "other", "description": "rain"})
        settings = Settings(generation_margin_threshold=10)
        tools = load_tools(settings)
        # The stub passes its second seed; the app's margin threshold still fails it.
        out = tools.generate(video, plan, root / "track.wav", settings.gen_seed + 1)
        result = tools.score_generation(out, plan, [sibling])
        self.assertFalse(result.passed)
        self.assertIn("below threshold 10", result.reason)
        # Without siblings there is no margin, so the threshold does not apply.
        self.assertTrue(tools.score_generation(out, plan, []).passed)
