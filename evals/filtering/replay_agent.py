"""Offline replay: the stem filter agent (filter=agent) vs SAM Audio Judge inside AUDYSSEY's
separate -> judge -> retry loop, on human-labelled StemFoley stems. No model calls.

Input: a results JSONL from the capstone stem_filter_agent run on 625 S3-labelled stems
(current625_results.jsonl). Each record has the agent's per-stage probabilities, the SAM Audio
Judge score of the same stem (meta.sam_judge_score) and the human labels (meta.human S1/S2/S3).
The data stays outside the repo; only aggregate numbers are written.

Agent decisions are recomputed from the stored stage probabilities with the vendored default
config (tools/filtering/stem_agent), so they follow exactly what filter=agent would decide.

usage: uv run python evals/filtering/replay_agent.py <current625_results.jsonl> [--out report.json]
"""

import json
import sys
from collections import defaultdict

import numpy as np

from audyssey.settings import Settings
from audyssey.tools.filtering.stem_agent import ACCEPT, HOLD, REJECT, load_config
from audyssey.tools.filtering.stem_agent.judge import FAIL, UNCERTAIN, band

GOOD = {"S1": "O", "S2": "O", "S3": "O"}


def agent_decision(rec: dict, cfg) -> str:
    scores = {s["stage"]: s["score"] for s in rec["stages"]}
    verdicts = [
        band(scores.get("presence"), False, cfg.presence.pass_at, cfg.presence.fail_at),
        band(scores.get("purity"), True, cfg.purity.pass_at, cfg.purity.fail_at),
        band(
            scores.get("completeness"),
            True,
            cfg.completeness.pass_at,
            cfg.completeness.fail_at,
        ),
    ]
    if FAIL in verdicts:
        return REJECT
    return HOLD if UNCERTAIN in verdicts else ACCEPT


def option(rec: dict) -> int:
    return int(rec["stem_id"].rsplit("option_", 1)[1])


def wilson(k: int, n: int) -> list:
    if n == 0:
        return [None, None]
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c, h = (
        (p + z * z / (2 * n)) / d,
        z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d,
    )
    return [round(float(c - h), 3), round(float(c + h), 3)]


def stem_level(recs, passed) -> dict:
    good = [r["good"] for r in recs]
    k = [g for g, p in zip(good, passed) if p]
    return {
        "passed": len(k),
        "pass_rate": round(len(k) / len(recs), 3),
        "precision": round(sum(k) / len(k), 3) if k else None,
        "precision_ci95": wilson(sum(k), len(k)),
        "recall_of_good": round(sum(k) / max(1, sum(good)), 3),
    }


def loop_replay(groups, rule, attempts: int) -> dict:
    """AUDYSSEY keeps the first passing attempt; if none passes, the last attempt with a warning."""
    passed_good = passed_bad = warned_good = warned_bad = 0
    for recs in groups.values():
        tried = sorted(recs, key=option)[:attempts]
        final = next((r for r in tried if rule(r)), None)
        if final is not None:
            passed_good += final["good"]
            passed_bad += not final["good"]
        else:
            last = tried[-1]
            warned_good += last["good"]
            warned_bad += not last["good"]
    n = len(groups)
    passed = passed_good + passed_bad
    return {
        "sources": n,
        "sources_passed": passed,
        "passed_precision": round(passed_good / passed, 3) if passed else None,
        "passed_precision_ci95": wilson(passed_good, passed),
        "bad_tracks_passed_silently": passed_bad,
        "sources_warned": n - passed,
        "good_tracks_among_warned": warned_good,
        "final_track_good_rate": round((passed_good + warned_good) / n, 3),
    }


def main(path: str, out: str | None) -> dict:
    cfg = load_config()
    recs = [json.loads(line) for line in open(path, encoding="utf-8")]
    for r in recs:
        r["good"] = all(r["meta"]["human"].get(k) == v for k, v in GOOD.items())
        r["agent"] = agent_decision(r, cfg)
        r["sam"] = float(r["meta"]["sam_judge_score"])
    stored = sum(r["agent"] == r["decision"] for r in recs)
    app_threshold = Settings().judge_pass_threshold
    n_accept = sum(r["agent"] == ACCEPT for r in recs)
    # SAM threshold that passes the same number of stems as the agent (descriptive comparison)
    matched = float(np.sort([r["sam"] for r in recs])[::-1][n_accept - 1])
    rules = {
        "no_judge": lambda r: True,
        f"sam_judge@{app_threshold}(app default)": lambda r: r["sam"] >= app_threshold,
        f"sam_judge@{matched:.3f}(same pass count as agent)": lambda r: (
            r["sam"] >= matched
        ),
        "agent(ACCEPT)": lambda r: r["agent"] == ACCEPT,
        "agent(ACCEPT+HOLD)": lambda r: r["agent"] != REJECT,
    }
    groups = defaultdict(list)
    for r in recs:
        groups[r["group_id"]].append(r)
    attempts = 1 + Settings().max_separation_retries
    good_any = sum(any(r["good"] for r in g) for g in groups.values())
    report = {
        "n_stems": len(recs),
        "good_rate": round(float(np.mean([r["good"] for r in recs])), 3),
        "agent_decisions": {
            d: sum(r["agent"] == d for r in recs) for d in (ACCEPT, HOLD, REJECT)
        },
        "agent_decisions_match_stored": f"{stored}/{len(recs)}",
        "sam_score_range": [
            round(min(r["sam"] for r in recs), 3),
            round(max(r["sam"] for r in recs), 3),
        ],
        "stem_level": {
            name: stem_level(recs, [rule(r) for r in recs])
            for name, rule in rules.items()
        },
        "loop_attempts": attempts,
        "sources_with_any_good_option": good_any,
        "loop_replay": {
            name: loop_replay(groups, rule, attempts) for name, rule in rules.items()
        },
    }
    if out:
        json.dump(
            report, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False
        )
    return report


if __name__ == "__main__":
    o = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    print(json.dumps(main(sys.argv[1], o), indent=1, ensure_ascii=False))
