"""Prepare synthetic controls and evaluate planning without running GPU tools.

Run `python -m audyssey.planning_eval --help`. Real model calls require --yes.
Synthetic references test audio evidence/policy, not general real-world quality.
"""

import argparse
import hashlib
import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field

from audyssey import trace
from audyssey.contracts import Model, PlanIssue, SourcePlan
from audyssey.media import probe, write_wav
from audyssey.settings import LLMEndpoint, Settings
from audyssey.tools.planning import Purpose, planning_scope
from audyssey.tools.planning.prompts import VERSION

Plan = Callable[[Path, Path, float, list[PlanIssue]], list[SourcePlan]]
Validate = Callable[[Path, Path, list[SourcePlan]], list[PlanIssue]]


class EvalCase(Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    visual: Literal["blink", "blank"]
    sound: Literal["beeps", "silence"]
    purpose: Purpose
    audio_available: bool
    source: SourcePlan
    expected: Literal["accept", "reject", "uncertain"]
    reference: Literal["synthetic", "needs_review"]
    expected_plan_count: int | None = Field(default=None, ge=0)

    @property
    def asset(self) -> str:
        return f"{self.visual}-{self.sound}.mkv"


def load_cases(path: Path) -> list[EvalCase]:
    cases = [
        EvalCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("empty dataset or duplicate case ids")
    return cases


def prepare(cases: list[EvalCase], out: Path) -> None:
    """Create three-second controls; audio variants copy the same video stream."""
    out.mkdir(parents=True, exist_ok=False)
    sample_rate = 48000
    beeps = np.zeros(sample_rate * 3, dtype=np.float32)
    for start in (1, 2):
        t = np.arange(sample_rate // 4) / sample_rate
        envelope = np.minimum(1, np.minimum(t, 0.25 - t) / 0.005)
        beeps[start * sample_rate : start * sample_rate + len(t)] = (
            0.4 * envelope * np.sin(2 * np.pi * 880 * t)
        )
    write_wav(out / "beeps.wav", beeps)
    write_wav(out / "silence.wav", np.zeros_like(beeps))
    for visual in sorted({case.visual for case in cases}):
        image_filter = "color=c=black:s=160x120:r=10:d=3"
        if visual == "blink":
            image_filter += ",drawbox=x=50:y=30:w=60:h=60:color=white:t=fill:enable='between(t,1,1.25)+between(t,2,2.25)'"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                image_filter,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(out / f"{visual}.mp4"),
            ],
            check=True,
            capture_output=True,
        )
    for visual, sound in sorted({(c.visual, c.sound) for c in cases}):
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(out / f"{visual}.mp4"),
                "-i",
                str(out / f"{sound}.wav"),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "pcm_s16le",
                "-shortest",
                str(out / f"{visual}-{sound}.mkv"),
            ],
            check=True,
            capture_output=True,
        )


def _endpoint(endpoint: LLMEndpoint) -> dict:
    return endpoint.model_dump(
        include={"api", "model", "input", "fps", "max_frames", "video_audio"}
    )


def _record(
    directory: Path, name: str, operation: Callable[[], list]
) -> tuple[list, str | None]:
    with trace.call(directory, name, "Planning evaluation", {}) as record:
        try:
            output = operation()
        except Exception as exc:
            # Provider bodies may echo credentials or media. Keep only the type.
            record.error = type(exc).__name__
            return [], record.error
        record.output = trace.describe(output, directory, record)
        return output, None


def run_eval(
    cases: list[EvalCase],
    fixtures: Path,
    out: Path,
    *,
    include_planning: bool = False,
    plan: Plan | None = None,
    validate: Validate | None = None,
) -> dict:
    """Record independent plan/count and candidate-validation experiments."""
    if out.exists():
        raise FileExistsError(out)
    assets = {fixtures / c.asset for c in cases} | {
        fixtures / f"{c.sound}.wav" for c in cases
    }
    for path in assets:
        if not path.is_file():
            raise FileNotFoundError(path)
    if validate is None or (include_planning and plan is None):
        from audyssey.tools.planning import real

        validate = validate or real.validate_plan
        plan = plan or real.plan
    settings = Settings()
    out.mkdir(parents=True)
    config = {
        "prompt_version": VERSION,
        "planner": _endpoint(settings.planner_endpoint()),
        "validator": _endpoint(settings.validator_endpoint()),
        "validator_context_s": settings.validator_context_s,
        "validator_audio_only": settings.validator_audio_only,
        "validator_audio": settings.validator_audio,
        "include_planning": include_planning,
        "cases_sha256": hashlib.sha256(
            "\n".join(c.model_dump_json() for c in cases).encode()
        ).hexdigest(),
        "assets_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(assets)
        },
    }
    (out / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    results = []
    for case in cases:
        directory = out / case.id
        directory.mkdir()
        video, audio = fixtures / case.asset, fixtures / f"{case.sound}.wav"
        started = time.perf_counter()
        predicted, plan_error = [], None
        with planning_scope(case.purpose, case.audio_available):
            if include_planning and plan is not None:
                predicted, plan_error = _record(
                    directory, "plan", lambda: plan(video, audio, probe(video)[0], [])
                )
            issues, error = _record(
                directory,
                "validate_plan",
                lambda: validate(video, audio, [case.source]),
            )
        result = "accept"
        if error or any(i.kind == "validation_error" for i in issues):
            result = "error"
        elif any(i.kind.startswith("validation_") for i in issues):
            result = "uncertain"
        elif issues:
            result = "reject"
        row = {
            "id": case.id,
            "purpose": case.purpose,
            "expected": case.expected,
            "reference": case.reference,
            "result": result,
            "error": error,
            "issues": [i.model_dump() for i in issues],
            "sources": [p.model_dump() for p in predicted],
            "plan_error": plan_error,
            "plan_count_match": (
                len(predicted) == case.expected_plan_count and plan_error is None
                if include_planning and case.expected_plan_count is not None
                else None
            ),
            "seconds": round(time.perf_counter() - started, 3),
        }
        results.append(row)
        with (out / "cases.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
    scored = [r for r in results if r["reference"] == "synthetic"]
    counts = [
        r["plan_count_match"] for r in scored if r["plan_count_match"] is not None
    ]
    negatives = [r for r in scored if r["expected"] == "reject"]
    summary = {
        "cases": len(results),
        "scored_cases": len(scored),
        "review_required": len(results) - len(scored),
        "validation_accuracy": sum(r["result"] == r["expected"] for r in scored)
        / len(scored)
        if scored
        else None,
        "false_approvals": sum(r["result"] == "accept" for r in negatives),
        "errors": sum(r["result"] == "error" for r in results),
        "plan_errors": sum(r["plan_error"] is not None for r in results),
        "source_count_accuracy": sum(counts) / len(counts) if counts else None,
        "seconds": sum(r["seconds"] for r in results),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("prepare", "run"):
        command = actions.add_parser(action)
        command.add_argument(
            "--cases", type=Path, default=Path("evals/planning/cases.jsonl")
        )
        command.add_argument("--out", type=Path, required=True)
        if action == "run":
            command.add_argument("--fixtures", type=Path, required=True)
            command.add_argument("--include-planning", action="store_true")
            command.add_argument(
                "--yes", action="store_true", help="Allow real LLM requests"
            )
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    if args.action == "prepare":
        prepare(cases, args.out)
        print(f"Prepared {len(cases)} cases in {args.out}; no model requests sent.")
        return
    if not args.yes:
        parser.error("No model requests sent. Pass --yes to allow real LLM evaluation.")
    summary = run_eval(
        cases, args.fixtures, args.out, include_planning=args.include_planning
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
