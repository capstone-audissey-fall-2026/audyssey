from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from functools import wraps
from pathlib import Path

from langsmith import traceable

from audyssey.contracts import (
    FilterResult,
    GroundResult,
    PlanIssue,
    SourcePlan,
    VisualHint,
)
from audyssey.settings import Settings


@dataclass(frozen=True)
class Tools:
    plan: Callable[[Path, Path, float, list[PlanIssue]], list[SourcePlan]]
    validate_plan: Callable[[Path, Path, list[SourcePlan]], list[PlanIssue]]
    # video: masked video for visual prompting, or None for text-only separation
    separate: Callable[[Path, SourcePlan, Path | None, Path, int], Path]
    judge: Callable[[Path, Path, SourcePlan], FilterResult]
    locate: Callable[[Path, VisualHint], GroundResult]
    mask_video: Callable[[Path, VisualHint, Path], Path]
    generate: Callable[[Path, SourcePlan, Path, int], Path]
    score_generation: Callable[[Path, SourcePlan, list[SourcePlan]], FilterResult]


def judge_verdict(result: FilterResult, threshold: float) -> FilterResult:
    """The app decides pass/fail from the judge's scores, not the tool server."""
    overall = result.scores.get("overall")
    if overall is None:
        return result.model_copy(
            update={"passed": False, "reason": result.reason or "no overall score"}
        )
    passed = overall >= threshold
    reason = "" if passed else f"judge overall {overall:.2f} < {threshold}"
    # Keep the tool's own explanation (e.g. which stage failed) unless it is only a
    # restatement of its own threshold check.
    if reason and result.reason and not result.reason.startswith("judge overall"):
        reason = f"{reason}: {result.reason}"
    return result.model_copy(update={"passed": passed, "reason": reason})


def generation_verdict(result: FilterResult, threshold: float) -> FilterResult:
    """Pass when the track is closest to its own description by at least threshold.

    Without siblings there is no margin and only text_correct counts.
    """
    correct = result.scores.get("text_correct") == 1
    margin = result.scores.get("text_margin")
    passed = correct and (margin is None or margin >= threshold)
    if passed:
        reason = ""
    elif not correct or margin is None:
        # The tool's reason names the closer sibling; it does not depend on the threshold.
        reason = result.reason or "generated track does not match its description"
    else:
        reason = f"text margin {margin:.3f} below threshold {threshold}"
    return result.model_copy(update={"passed": passed, "reason": reason})


def load_tools(settings: Settings) -> Tools:
    for mode, url, name in [
        (settings.separator, settings.separator_url, "SEPARATOR"),
        (settings.filter, settings.filter_url, "FILTER"),
        (settings.grounder, settings.grounding_url, "GROUNDING"),
        (settings.generator, settings.generator_url, "GENERATOR"),
    ]:
        if mode == "remote" and not url.strip():
            raise ValueError(f"AUDYSSEY_{name}_URL is required for remote mode")
    if settings.filter == "agent" and not settings.stem_agent_url.strip():
        raise ValueError("AUDYSSEY_STEM_AGENT_URL is required for filter=agent")
    planning = import_module(f"audyssey.tools.planning.{settings.planner}")
    separation = import_module(f"audyssey.tools.separation.{settings.separator}")
    filtering = import_module(f"audyssey.tools.filtering.{settings.filter}")
    grounding = import_module(f"audyssey.tools.grounding.{settings.grounder}")
    generation = import_module(f"audyssey.tools.generation.{settings.generator}")

    # Tool servers may run elsewhere with their own settings; thresholds are the app's.
    @wraps(filtering.judge)
    def judge(mono: Path, track: Path, plan: SourcePlan) -> FilterResult:
        result = filtering.judge(mono, track, plan)
        return judge_verdict(result, settings.judge_pass_threshold)

    @wraps(generation.score_generation)
    def score_generation(
        track: Path, plan: SourcePlan, siblings: list[SourcePlan]
    ) -> FilterResult:
        result = generation.score_generation(track, plan, siblings)
        return generation_verdict(result, settings.generation_margin_threshold)

    return Tools(
        wraps(planning.plan)(traceable(run_type="tool", name="plan")(planning.plan)),
        wraps(planning.validate_plan)(
            traceable(run_type="tool", name="validate_plan")(planning.validate_plan)
        ),
        wraps(separation.separate)(
            traceable(run_type="tool", name="separate")(separation.separate)
        ),
        wraps(judge)(traceable(run_type="tool", name="judge")(judge)),
        wraps(grounding.locate)(
            traceable(run_type="tool", name="locate")(grounding.locate)
        ),
        wraps(grounding.mask_video)(
            traceable(run_type="tool", name="mask_video")(grounding.mask_video)
        ),
        wraps(generation.generate)(
            traceable(run_type="tool", name="generate")(generation.generate)
        ),
        wraps(score_generation)(
            traceable(run_type="tool", name="score_generation")(score_generation)
        ),
    )
