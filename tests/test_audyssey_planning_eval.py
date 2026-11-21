import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audyssey.contracts import PlanIssue


class PlanningEvalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_prepare_makes_controlled_audio_and_identical_visual_streams(self):
        import subprocess
        import numpy as np
        from audyssey.media import read_wav
        from audyssey.planning_eval import load_cases, prepare

        cases = load_cases(Path("evals/planning/cases.jsonl"))
        fixtures = self.root / "fixtures"
        prepare(cases, fixtures)
        self.assertEqual(len(cases), 8)
        silent = read_wav(fixtures / "silence.wav")
        beeps = read_wav(fixtures / "beeps.wav")
        self.assertEqual(np.max(np.abs(silent)), 0)
        self.assertGreater(np.max(np.abs(beeps[48000:60000])), 0.1)
        self.assertEqual(np.max(np.abs(beeps[:48000])), 0)

        def frames(asset):
            return subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(fixtures / asset), "-map", "0:v", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                check=True, capture_output=True,
            ).stdout
        self.assertEqual(frames("blink-beeps.mkv"), frames("blink-silence.mkv"))
        # Exercise the real input conversion too; merely decoding the generated
        # fixtures missed a re-encoding stall with the Windows development FFmpeg.
        from audyssey.media import planner_clip
        run = subprocess.run
        def bounded(*args, **kwargs):
            kwargs["timeout"] = 10
            return run(*args, **kwargs)
        with patch("audyssey.media.subprocess.run", side_effect=bounded):
            planner_clip(fixtures / "blink-beeps.mkv", fixtures / "planner-input.mp4", True)

    def test_model_visible_names_do_not_leak_reference_labels(self):
        from audyssey.planning_eval import load_cases

        cases = load_cases(Path("evals/planning/cases.jsonl"))
        self.assertEqual([case.source.name for case in cases], [f"candidate_{i:02}" for i in range(1, 9)])

    def test_eval_records_errors_separately_and_does_not_score_unreviewed_cases(self):
        from audyssey.planning_eval import load_cases, run_eval
        from audyssey.tools.planning import current_request

        cases = load_cases(Path("evals/planning/cases.jsonl"))
        expected = {case.source.name: case for case in cases}
        seen = []

        def validate(video, audio, plans):
            case = expected[plans[0].name]
            seen.append((case.id, current_request().purpose, current_request().audio_available))
            if case.id == "visible-silent":
                raise RuntimeError("private provider response")
            if case.expected == "accept":
                return []
            return [PlanIssue(source_name=case.source.name,
                              kind="not_found" if case.expected == "reject" else "validation_unavailable",
                              message="synthetic reference")]

        fixtures = self.root / "fixtures"
        fixtures.mkdir()
        for case in cases:
            (fixtures / case.asset).touch()
            (fixtures / f"{case.sound}.wav").touch()
        out = self.root / "run"
        with patch("audyssey.planning_eval.probe", return_value=(3.0, 1)):
            summary = run_eval(cases, fixtures, out, validate=validate)
        self.assertEqual(summary["scored_cases"], 7)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["validation_accuracy"], 6 / 7)
        self.assertEqual(summary["review_required"], 1)
        self.assertEqual(len(seen), 8)
        self.assertTrue(any(purpose == "generate" for _, purpose, _ in seen))
        self.assertEqual(current_request().purpose, "separate")
        self.assertNotIn("private provider response", (out / "cases.jsonl").read_text())
        config = json.loads((out / "config.json").read_text())
        self.assertIn("prompt_version", config)
        self.assertNotIn("api_key", json.dumps(config))
        with self.assertRaises(FileExistsError):
            run_eval(cases, fixtures, out, validate=validate)

    def test_cli_requires_explicit_opt_in_before_any_real_model_call(self):
        from audyssey.planning_eval import main

        with patch("audyssey.planning_eval.run_eval") as run:
            with self.assertRaises(SystemExit) as caught:
                main(["run", "--fixtures", str(self.root), "--out", str(self.root / "out")])
        self.assertEqual(caught.exception.code, 2)
        run.assert_not_called()

    def test_cases_reject_duplicate_ids(self):
        from audyssey.planning_eval import load_cases

        line = Path("evals/planning/cases.jsonl").read_text(encoding="utf-8").splitlines()[0]
        path = self.root / "cases.jsonl"
        path.write_text(line + "\n" + line, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_cases(path)
