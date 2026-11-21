import json
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Literal
from dataclasses import dataclass, replace

from langsmith import traceable
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from audyssey import trace
from audyssey.contracts import (
    AddSource,
    Command,
    Drop,
    Generate,
    Job,
    Keep,
    PlanIssue,
    Render,
    Reseparate,
    SetGain,
    SetPitch,
    Source,
    SourcePlan,
    StepStatus,
)
from audyssey.media import compute_peaks, extract_audio, is_silent, probe, write_silence
from audyssey.settings import Settings
from audyssey.store import JobStore
from audyssey.tools import Tools, load_tools
from audyssey.tools.planning import planning_scope
from audyssey.tools.editing.render import compute_residual, render


@dataclass
class Context:
    tools: Tools
    settings: Settings
    store: JobStore


def check_plans(
    plans: list[SourcePlan], duration: float
) -> tuple[list[SourcePlan], list[PlanIssue]]:
    merged: dict[str, SourcePlan] = {}
    for plan in plans:
        if plan.name in merged:
            merged[plan.name].spans.extend(plan.spans)
        else:
            merged[plan.name] = plan.model_copy(deep=True)
    issues = []
    for plan in merged.values():
        if not plan.description.strip():
            issues.append(
                PlanIssue(
                    source_name=plan.name,
                    kind="empty_description",
                    message="description must not be empty",
                )
            )
        if any(span.end > duration for span in plan.spans):
            issues.append(
                PlanIssue(
                    source_name=plan.name,
                    kind="span_out_of_range",
                    message="span exceeds video duration",
                )
            )
    return list(merged.values()), issues


def update_step(job: Job, ctx: Context, step: StepStatus) -> None:
    if step.status == "running":
        trace.set_step(step.key)
    job.steps = [s for s in job.steps if s.key != step.key] + [step]
    ctx.store.save(job)


def siblings(job: Job, source: Source) -> list[SourcePlan]:
    return [
        other.plan
        for other in job.sources
        if other.id not in {source.id, source.replaces}
        and other.plan.kind != "dialogue"
    ]


def generate_source(job: Job, source: Source, ctx: Context) -> None:
    if source.plan.kind == "dialogue":
        source.status, source.track_path = "skipped", None
        update_step(
            job,
            ctx,
            StepStatus(
                key=f"generate:{source.id}",
                status="done",
                message="dialogue is not generated",
            ),
        )
        return
    directory = ctx.store.dir(job.id)
    maximum = 1 + ctx.settings.max_generation_retries
    source.status = "running"
    best_path: Path | None = None
    best_result = None
    attempts: list[Path] = []
    messages: list[str] = []
    key = f"generate:{source.id}"
    try:
        for round_number in range(1, maximum + 1):
            source.attempts += 1
            key = f"generate:{source.id}"
            update_step(
                job,
                ctx,
                StepStatus(
                    key=key, status="running", round=round_number, max_rounds=maximum
                ),
            )
            out = directory / f"tracks/{source.id}.attempt{source.attempts}.wav"
            attempts.append(out)
            path = ctx.tools.generate(
                directory / job.video_path,
                source.plan,
                out,
                ctx.settings.gen_seed + source.attempts - 1,
            )
            update_step(
                job,
                ctx,
                StepStatus(
                    key=key, status="done", round=round_number, max_rounds=maximum
                ),
            )
            key = f"score:{source.id}"
            update_step(
                job,
                ctx,
                StepStatus(
                    key=key,
                    status="running",
                    round=round_number,
                    max_rounds=maximum,
                    message="; ".join(messages),
                ),
            )
            result = ctx.tools.score_generation(
                path,
                source.plan,
                siblings(job, source),
            )
            messages.append(
                f"attempt {source.attempts}: correct={result.scores.get('text_correct')} "
                f"margin={result.scores.get('text_margin')} {result.reason}".rstrip()
            )
            if best_result is None or result.scores.get(
                "text_margin", 0
            ) >= best_result.scores.get("text_margin", 0):
                best_path, best_result = path, result
            update_step(
                job,
                ctx,
                StepStatus(
                    key=key,
                    status="done" if result.passed else "warning",
                    round=round_number,
                    max_rounds=maximum,
                    message="; ".join(messages),
                ),
            )
            if result.passed:
                break
        if best_path is None:
            raise RuntimeError("generation produced no track")
        final = directory / f"tracks/{source.id}.wav"
        best_path.replace(final)
        source.track_path = final.relative_to(directory).as_posix()
        source.filter = best_result
        source.status = "done"
    except Exception as exc:
        source.status, source.track_path = "failed", None
        update_step(
            job,
            ctx,
            StepStatus(
                key=key,
                status="failed",
                round=round_number,
                max_rounds=maximum,
                message=str(exc),
            ),
        )
    finally:
        for path in attempts:
            path.unlink(missing_ok=True)
    ctx.store.save(job)


def process_source(job: Job, source: Source, ctx: Context) -> None:
    if job.silent or source.origin == "generated":
        generate_source(job, source, ctx)
        return
    directory = ctx.store.dir(job.id)
    maximum = ctx.settings.max_separation_retries + 1
    source.status = "running"
    masked_for, video = None, None
    try:
        while True:
            source.attempts += 1
            update_step(
                job,
                ctx,
                StepStatus(
                    key=f"separate:{source.id}",
                    status="running",
                    round=source.attempts,
                    max_rounds=maximum,
                ),
            )
            hint = source.plan.visual_hint if ctx.settings.visual_prompt else None
            if hint is None:
                video = None
            elif hint != masked_for:
                # Masking runs SAM3 over the whole clip; reuse it while the hint holds.
                video = ctx.tools.mask_video(
                    directory / job.video_path,
                    hint,
                    directory / f"masks/{source.id}.mp4",
                )
                masked_for = hint
            path = ctx.tools.separate(
                directory / job.mono_path,
                source.plan,
                video,
                directory / f"tracks/{source.id}.wav",
                source.attempts,
            )
            source.track_path = path.relative_to(directory).as_posix()
            update_step(
                job,
                ctx,
                StepStatus(
                    key=f"separate:{source.id}",
                    status="done",
                    round=source.attempts,
                    max_rounds=maximum,
                ),
            )
            update_step(
                job,
                ctx,
                StepStatus(
                    key=f"judge:{source.id}",
                    status="running",
                    round=source.attempts,
                    max_rounds=maximum,
                ),
            )
            source.filter = ctx.tools.judge(
                directory / job.mono_path, path, source.plan
            )
            update_step(
                job,
                ctx,
                StepStatus(
                    key=f"judge:{source.id}",
                    status="done" if source.filter.passed else "warning",
                    round=source.attempts,
                    max_rounds=maximum,
                    message=source.filter.reason,
                ),
            )
            if source.filter.passed or source.attempts >= maximum:
                break
            if source.filter.suggestion is not None:
                source.plan = source.filter.suggestion
        source.status = "done"
    except Exception as exc:
        source.status = "failed"
        source.track_path = None
        key = (
            f"judge:{source.id}"
            if any(
                s.key == f"judge:{source.id}" and s.status == "running"
                for s in job.steps
            )
            else f"separate:{source.id}"
        )
        update_step(
            job,
            ctx,
            StepStatus(
                key=key,
                status="failed",
                round=source.attempts,
                max_rounds=maximum,
                message=str(exc),
            ),
        )
    ctx.store.save(job)


class AnalysisInput(BaseModel):
    job_id: str = ""
    job: Job | None = None
    method: Literal["separate", "generate"] | None = "separate"


class AnalysisState(BaseModel):
    job: Job
    method: Literal["separate", "generate"] | None = "separate"
    issues: list[PlanIssue] = Field(default_factory=list)
    round: int = 0


def refresh_residual(job: Job, ctx: Context) -> None:
    # Generation replaces the soundtrack; the original stays available as the source audio.
    if job.silent or job.method == "generate":
        job.residual.path = None
        return
    directory = ctx.store.dir(job.id)
    update_step(job, ctx, StepStatus(key="residual", status="running"))
    tracks = [
        directory / s.track_path
        for s in job.sources
        if s.origin == "separated" and s.track_path
    ]
    audio = directory / job.audio_path
    inputs = {"audio": audio, "tracks": tracks}
    with trace.step(directory, "residual", trace.describe(inputs, directory)) as record:
        out = compute_residual(audio, tracks, directory / "residual.wav")
        record.output = trace.describe(out, directory, record)
    job.residual.path = "residual.wav"
    update_step(job, ctx, StepStatus(key="residual", status="done"))


def build_graph(
    ctx: Context | None = None,
    *,
    on_finish: Callable[[], None] = lambda: None,
) -> CompiledStateGraph:
    """Build a reusable analysis graph without starting a job or loading models.

    Inputs accept either a stored job_id or a live/serialized Job. Each invocation
    owns its job state; only tools, settings and the store are shared.
    """
    if ctx is None:
        settings = Settings()
        ctx = Context(load_tools(settings), settings, JobStore(settings.work_dir))
    context = ctx

    def prepare(state: AnalysisInput) -> dict:
        job = context.store.load(state.job_id) if state.job_id else state.job
        if job is None:
            raise ValueError("job_id or job is required")
        job.state, job.error = "running", None
        if state.method is not None:
            job.method = "generate" if job.silent else state.method
        return {"job": job, "method": state.method, "issues": [], "round": 0}

    def job_context(job: Job) -> Context:
        directory = context.store.dir(job.id)
        return replace(
            context,
            tools=trace.wrap_tools(context.tools, directory, context.settings),
        )

    def preprocess(state: AnalysisState) -> dict:
        job = state.job
        directory = context.store.dir(job.id)
        update_step(job, ctx, StepStatus(key="preprocess", status="running"))
        video = {"video": trace.describe(directory / job.video_path, directory)}
        with trace.step(directory, "preprocess", video) as record:
            extract(job, directory, record)
        update_step(job, ctx, StepStatus(key="preprocess", status="done"))
        return {"job": job}

    def extract(job: Job, directory: Path, record: trace.Call) -> None:
        duration, channels = probe(directory / job.video_path)
        job.duration = duration
        if channels == 0:
            write_silence(directory / "audio.wav", duration, 2)
            write_silence(directory / "mono.wav", duration, 1)
            job.silent = True
        else:
            extract_audio(directory / job.video_path, directory / "audio.wav", False)
            extract_audio(directory / job.video_path, directory / "mono.wav", True)
            job.silent = is_silent(directory / "audio.wav")
            if job.silent:
                write_silence(directory / "audio.wav", duration, channels)
                write_silence(directory / "mono.wav", duration, 1)
        job.audio_path, job.mono_path, job.peaks_path = (
            "audio.wav",
            "mono.wav",
            "peaks.json",
        )
        (directory / job.peaks_path).write_text(
            json.dumps(compute_peaks(directory / job.audio_path))
        )
        record.output = {
            "duration": duration,
            "channels": channels,
            "silent": job.silent,
            "audio": trace.describe(directory / job.audio_path, directory),
            "mono": trace.describe(directory / job.mono_path, directory),
        }

    def plan(state: AnalysisState) -> dict:
        job = state.job
        ctx = job_context(job)
        directory = ctx.store.dir(job.id)
        round_number = state.round + 1
        update_step(
            job,
            ctx,
            StepStatus(
                key="plan",
                status="running",
                round=round_number,
                max_rounds=ctx.settings.max_plan_rounds,
            ),
        )
        with planning_scope(job.method or "separate", not job.silent):
            plans, issues = check_plans(
                ctx.tools.plan(
                    directory / job.video_path,
                    directory / job.audio_path,
                    job.duration,
                    state.issues,
                ),
                job.duration,
            )
        previous = {source.plan.name: source for source in job.sources}
        origin = "generated" if job.silent or job.method == "generate" else "separated"
        sources = []
        for i, plan_item in enumerate(plans, 1):
            source = previous.get(plan_item.name)
            if source is None:
                source = Source(
                    id=f"s{i}",
                    plan=plan_item,
                    origin=origin,
                )
            else:
                source.id, source.plan = f"s{i}", plan_item
                if source.origin != origin:
                    source.origin, source.status = origin, "pending"
                    source.attempts = 0
                    source.track_path, source.filter = None, None
            sources.append(source)
        job.sources = sources
        update_step(
            job,
            ctx,
            StepStatus(
                key="plan",
                status="done",
                round=round_number,
                max_rounds=ctx.settings.max_plan_rounds,
            ),
        )
        return {"job": job, "issues": issues, "round": round_number}

    def validate(state: AnalysisState) -> dict:
        job = state.job
        ctx = job_context(job)
        directory = ctx.store.dir(job.id)
        active_key = "validate_plan"
        update_step(
            job,
            ctx,
            StepStatus(
                key=active_key,
                status="running",
                round=state.round,
                max_rounds=ctx.settings.max_plan_rounds,
            ),
        )
        with planning_scope(job.method or "separate", not job.silent):
            issues = state.issues or ctx.tools.validate_plan(
                directory / job.video_path,
                directory / job.audio_path,
                [s.plan for s in job.sources],
            )
        for source in job.sources:
            hint = source.plan.visual_hint
            if hint is None or not ctx.settings.visual_prompt:
                continue
            try:
                found = ctx.tools.locate(directory / job.video_path, hint).found
                message = "visual hint target was not found"
            except Exception as exc:
                found, message = False, str(exc)
            if not found:
                issues.append(
                    PlanIssue(
                        source_name=source.plan.name,
                        kind="visual_hint_not_found",
                        message=message,
                    )
                )
        job.plan_issues = issues
        update_step(
            job,
            ctx,
            StepStatus(
                key=active_key,
                status="warning" if issues else "done",
                round=state.round,
                max_rounds=ctx.settings.max_plan_rounds,
                message="; ".join(i.message for i in issues),
            ),
        )
        if issues and state.round >= ctx.settings.max_plan_rounds:
            update_step(
                job,
                ctx,
                StepStatus(
                    key="plan",
                    status="warning",
                    round=state.round,
                    max_rounds=ctx.settings.max_plan_rounds,
                    message="; ".join(i.message for i in issues),
                ),
            )
        return {"job": job, "issues": issues}

    def separate(state: AnalysisState) -> dict:
        job = state.job
        ctx = job_context(job)
        # ponytail: sequential per-source loop, fan out with Send when real GPU tools need parallelism
        for source in job.sources:
            unresolved = [
                issue
                for issue in job.plan_issues
                if issue.source_name is None or issue.source_name == source.plan.name
            ]
            if unresolved:
                source.status, source.track_path, source.filter = "skipped", None, None
                key = "generate" if source.origin == "generated" else "separate"
                update_step(
                    job,
                    ctx,
                    StepStatus(
                        key=f"{key}:{source.id}",
                        status="warning",
                        message="Source not validated; skipped: "
                        + "; ".join(i.message for i in unresolved),
                    ),
                )
                continue
            process_source(job, source, ctx)
        return {"job": job}

    def residual(state: AnalysisState) -> dict:
        refresh_residual(state.job, context)
        return {"job": state.job}

    def finish(state: AnalysisState) -> dict:
        on_finish()
        job = state.job
        job.state = "new" if state.method is None else "ready"
        context.store.save(job)
        return {"job": job}

    def guarded(name: str, node: Callable[[AnalysisState], dict]) -> Callable:
        @wraps(node)
        def run(state: AnalysisState) -> dict:
            try:
                return node(state)
            except Exception as exc:
                on_finish()
                job = state.job
                job.state, job.error = "failed", str(exc)
                key = "validate_plan" if name == "validate" else name
                update_step(
                    job, context, StepStatus(key=key, status="failed", message=str(exc))
                )
                raise

        return run

    builder = StateGraph(AnalysisState, input_schema=AnalysisInput)
    builder.add_node("prepare", prepare)
    for name, node in [
        ("preprocess", preprocess),
        ("plan", plan),
        ("validate", validate),
        ("separate", separate),
        ("residual", residual),
    ]:
        builder.add_node(name, guarded(name, node))
    builder.add_node("finish", finish)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges(
        "prepare",
        lambda state: (
            "preprocess" if state.method is None or not state.job.audio_path else "plan"
        ),
        ["preprocess", "plan"],
    )
    builder.add_conditional_edges(
        "preprocess",
        lambda state: "finish" if state.method is None else "plan",
        ["finish", "plan"],
    )
    builder.add_edge("plan", "validate")
    builder.add_conditional_edges(
        "validate",
        lambda state: (
            "plan"
            if state.issues and state.round < context.settings.max_plan_rounds
            else "separate"
        ),
        ["plan", "separate"],
    )
    builder.add_edge("separate", "residual")
    builder.add_edge("residual", "finish")
    builder.add_edge("finish", END)
    return builder.compile().with_config(
        {"recursion_limit": 2 * context.settings.max_plan_rounds + 10}
    )


def analyze(
    job: Job,
    ctx: Context,
    on_finish: Callable[[], None] = lambda: None,
    method: Literal["separate", "generate"] | None = "separate",
) -> Job:
    """Run the shared graph and release the API lock before publishing completion."""
    finished = False

    def finish() -> None:
        nonlocal finished
        if not finished:
            finished = True
            on_finish()

    try:
        build_graph(ctx, on_finish=finish).invoke(
            {"job": job, "method": method},
        )
    except Exception as exc:
        error = str(exc)
        finish()
        if job.state != "failed" or job.error != error:
            active_key = job.steps[-1].key if job.steps else "preprocess"
            job.state, job.error = "failed", error
            update_step(
                job, ctx, StepStatus(key=active_key, status="failed", message=error)
            )
    finally:
        finish()
    return job


def generation_plan(
    job: Job, source: Source, description: str | None
) -> tuple[Source, SourcePlan]:
    target_source = source
    if source.origin == "separated":
        replacement = next(
            (
                s
                for s in job.sources
                if s.origin == "generated" and s.replaces == source.id
            ),
            None,
        )
        target_source = replacement or Source(
            id=f"s{max(int(s.id[1:]) for s in job.sources) + 1}",
            plan=source.plan.model_copy(deep=True),
            origin="generated",
            replaces=source.id,
        )
    plan = target_source.plan.model_copy(deep=True)
    if source.origin == "separated":
        plan.name = source.plan.name + " (generated)"
    if description is not None:
        plan.description = description
    return target_source, plan


def reseparation_plan(source: Source, cmd: Reseparate) -> SourcePlan:
    plan = source.plan.model_copy(deep=True)
    if cmd.description is not None:
        plan.description = cmd.description
    if cmd.spans is not None:
        plan.spans = cmd.spans
    return plan


def check_command(job: Job, cmd: Command) -> None:
    """Raise KeyError or ValueError if cmd is invalid; never mutates job."""
    if isinstance(cmd, AddSource):
        if job.silent and cmd.method == "separate":
            raise ValueError("silent videos only support generation")
        if cmd.method == "generate" and cmd.plan.kind == "dialogue":
            raise ValueError("dialogue is not generated")
        _, issues = check_plans([cmd.plan], job.duration)
        if issues:
            raise ValueError("; ".join(i.message for i in issues))
        if any(s.plan.name == cmd.plan.name for s in job.sources):
            raise ValueError("source name already exists; use reseparate")
    elif not isinstance(cmd, Render):
        source = job.find_source(cmd.source_id)
        if (job.residual if cmd.source_id == "residual" else source) is None:
            raise KeyError(cmd.source_id)
        if isinstance(cmd, Generate):
            if source is None:
                raise ValueError("residual cannot be generated")
            if source.plan.kind == "dialogue":
                raise ValueError("dialogue is not generated")
            _, plan = generation_plan(job, source, cmd.description)
            _, issues = check_plans([plan], job.duration)
            if issues:
                raise ValueError("; ".join(i.message for i in issues))
        elif isinstance(cmd, SetPitch):
            if source is None:
                raise ValueError("residual does not support pitch")
        elif isinstance(cmd, Reseparate):
            if source is None:
                raise ValueError("residual cannot be reseparated")
            if job.silent or source.origin == "generated":
                raise ValueError(
                    "generated sources and silent videos cannot be reseparated"
                )
            _, issues = check_plans([reseparation_plan(source, cmd)], job.duration)
            if issues:
                raise ValueError("; ".join(i.message for i in issues))


def handle_command(job: Job, cmd: Command, ctx: Context) -> Job:
    check_command(job, cmd)
    directory = ctx.store.dir(job.id)
    ctx = replace(ctx, tools=trace.wrap_tools(ctx.tools, directory, ctx.settings))
    if isinstance(cmd, Render):
        update_step(job, ctx, StepStatus(key="render", status="running"))
        try:
            mix = [
                {
                    "source": s.id,
                    "keep": s.keep,
                    "gain": s.gain,
                    "pitch": s.pitch_semitones,
                }
                for s in job.sources
            ]
            with trace.step(directory, "render", {"sources": mix}) as record:
                job.outputs = render(job, directory, cmd.include_residual_stem)
                outputs = job.outputs
                record.output = trace.describe(
                    {
                        "video": directory / outputs.video_mp4,
                        "mix": directory / outputs.mix_wav,
                        "stems": [directory / stem for stem in outputs.stems],
                    },
                    directory,
                )
        except Exception as exc:
            update_step(
                job, ctx, StepStatus(key="render", status="failed", message=str(exc))
            )
            raise
        update_step(job, ctx, StepStatus(key="render", status="done"))
    elif isinstance(cmd, AddSource):
        plans, _ = check_plans([cmd.plan], job.duration)
        number = max((int(s.id[1:]) for s in job.sources), default=0) + 1
        source = Source(
            id=f"s{number}",
            plan=plans[0],
            origin="generated" if cmd.method == "generate" else "separated",
        )
        job.sources.append(source)
        process_source(job, source, ctx)
        if cmd.method == "separate":
            refresh_residual(job, ctx)
    else:
        source = job.find_source(cmd.source_id)
        target = job.residual if cmd.source_id == "residual" else source
        assert target is not None
        if isinstance(cmd, Generate):
            assert source is not None
            target_source, plan = generation_plan(job, source, cmd.description)
            target_source.plan = plan
            if target_source not in job.sources:
                job.sources.append(target_source)
            if target_source.replaces:
                # The separated stem stays for comparison; the new generation plays.
                original = job.find_source(target_source.replaces)
                if original is not None:
                    original.keep = False
                target_source.keep = True
            generate_source(job, target_source, ctx)
        elif isinstance(cmd, (Keep, Drop)):
            target.keep = isinstance(cmd, Keep)
        elif isinstance(cmd, SetGain):
            target.gain = cmd.gain
        elif isinstance(cmd, SetPitch):
            assert source is not None
            source.pitch_semitones = cmd.semitones
        elif isinstance(cmd, Reseparate):
            assert source is not None
            plan = reseparation_plan(source, cmd)
            source.plan, source.attempts = plan, 0
            process_source(job, source, ctx)
            refresh_residual(job, ctx)
    return ctx.store.save(job)


# Preserve the callable signature across LangSmith's extra-keyword protocol.
handle_command: Callable[[Job, Command, Context], Job] = wraps(handle_command)(
    traceable(
        name="command",
        process_inputs=lambda inputs: {
            "job_id": inputs["job"].id,
            "command": inputs["cmd"].model_dump(),
        },
    )(handle_command)
)
