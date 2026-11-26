import json
import os
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

import typer
from pydantic import ValidationError
import uvicorn

from audyssey.api import create_app
from audyssey.routing_eval import (
    INPUT_TOKENS_PER_CALL,
    git_sha,
    load_cases,
    run_eval,
    uncached_calls,
)
from audyssey.settings import Settings
from audyssey.tools.routing import cache_salt, load_router, model_name
from audyssey.toolserver import create_tool_app


class Tool(str, Enum):
    separation = "separation"
    filtering = "filtering"
    grounding = "grounding"
    generation = "generation"


app = typer.Typer()


@app.callback()
def callback() -> None:
    """Audyssey audio editing skeleton."""


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8600) -> None:
    uvicorn.run(create_app(), host=host, port=port)


@app.command()
def tool_server(
    tool: Annotated[list[Tool], typer.Option()],
    impl: Annotated[Literal["stub", "real"], typer.Option()] = "stub",
    host: str = "127.0.0.1",
    port: int = 8700,
) -> None:
    token = Settings().tool_token
    if host not in {"127.0.0.1", "localhost", "::1"} and not token:
        typer.echo(
            "AUDYSSEY_TOOL_TOKEN is required when binding to a non-loopback host"
        )
        raise typer.Exit(1)
    uvicorn.run(
        create_tool_app([item.value for item in tool], impl, token),
        host=host,
        port=port,
    )


MAX_TEST_OPENS = 3


@app.command()
def eval_routing(
    out: Annotated[Path, typer.Option()],
    split: Annotated[Literal["train", "dev", "test"], typer.Option()],
    router: Annotated[Literal["stub", "real", "hybrid"], typer.Option()] = "stub",
    k: int = 5,
    yes: bool = False,
    cases: Path = Path("evals/routing/cases.jsonl"),
    fixtures: Path = Path("evals/routing/fixtures"),
    guard: bool = False,
) -> None:
    """Route each labeled case k times without executing commands."""

    def fail(message: str) -> typer.Exit:
        typer.echo(message)
        return typer.Exit(1)

    if out.exists():
        raise fail(f"{out} already exists; results are never overwritten")
    all_cases = load_cases(cases)
    if any(c.split is None for c in all_cases):
        raise fail("some cases have no split; run assign_splits first")
    selected = [c for c in all_cases if c.split == split]
    if not selected:
        raise fail(f"no cases in split {split}")
    # Unguarded: run_eval applies --guard after the cache read. Built through
    # the constructor so the Settings validators run.
    try:
        settings = Settings(router=router, router_guard=False)
    except ValidationError as exc:
        # The message only: the full error echoes the input, which can hold keys.
        raise fail(exc.errors()[0]["msg"]) from None
    model = model_name(settings)
    effort = settings.router_reasoning_effort
    salt = cache_salt(router)
    cache = cases.parent / "cache"
    if router != "stub":
        calls = uncached_calls(
            model, selected, k, cache, settings.router_format, effort, salt
        )
        if not yes:
            raise fail(
                f"{calls} uncached calls, about {calls * INPUT_TOKENS_PER_CALL} "
                "input tokens; rerun with --yes to pay for them"
            )
        if split == "test":
            log = cases.parent / "test_opens.jsonl"
            opens = log.read_text().splitlines() if log.exists() else []
            used = sum(json.loads(line).get("model") == model for line in opens)
            if used >= MAX_TEST_OPENS:
                raise fail(
                    f"model {model}: all {MAX_TEST_OPENS} opens of the test split "
                    "are used"
                )
    run_eval(
        load_router(settings),
        model,
        router,
        selected,
        fixtures,
        k,
        out,
        cache if router != "stub" else None,
        settings.router_format,
        guard,
        effort,
        salt,
    )
    if router != "stub" and split == "test":
        entry = {
            "date": datetime.now(UTC).isoformat(),
            "model": model,
            "git_sha": git_sha(),
            "out": str(out),
        }
        with log.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    typer.echo(f"wrote {out}")


@app.command()
def improve_routing(
    out: Annotated[Path, typer.Option()],
    rounds: int = 5,
    yes: bool = False,
    cases: Path = Path("evals/routing/cases.jsonl"),
    fixtures: Path = Path("evals/routing/fixtures"),
) -> None:
    """Rewrite the routing descriptions from train failures; adopt on dev."""

    def fail(message: str) -> typer.Exit:
        typer.echo(message)
        return typer.Exit(1)

    if out.exists():
        raise fail(f"{out} already exists; results are never overwritten")
    all_cases = load_cases(cases)
    if any(c.split is None for c in all_cases):
        raise fail("some cases have no split; run assign_splits first")
    train = [c for c in all_cases if c.split == "train"]
    dev = [c for c in all_cases if c.split == "dev"]
    if not train or not dev:
        raise fail("train and dev splits must both have cases")
    variables = {
        "base_url": "AUDYSSEY_IMPROVER_BASE_URL",
        "model": "AUDYSSEY_IMPROVER_MODEL",
        "api_key": "AUDYSSEY_IMPROVER_API_KEY",
    }
    for name in variables.values():
        if not os.environ.get(name):
            raise fail(f"{name} is required")
    router_calls = len(dev) + rounds * (len(train) + len(dev))
    if not yes:
        raise fail(
            f"up to {router_calls} router calls and {rounds} improver calls; "
            "rerun with --yes to pay for them"
        )
    try:
        settings = Settings(router="real", router_guard=False)
        endpoint = settings.router_endpoint()
        improver = (
            Settings()
            .planner_endpoint()
            .model_copy(
                update={"api": "openai"}
                | {k: os.environ[v] for k, v in variables.items()}
            )
        )
    except ValidationError as exc:
        # The message only: the full error echoes the input, which can hold keys.
        raise fail(exc.errors()[0]["msg"]) from None
    # LLM SDKs are optional; the GPU tool server only installs audyssey[ui].
    from audyssey.routing_improve import improve
    from audyssey.tools.routing.real import route as real_route

    effort, fmt = settings.router_reasoning_effort, settings.router_format
    improve(
        lambda d: (
            lambda request, job: real_route(
                request, job, endpoint, reasoning_effort=effort, fmt=fmt, descriptions=d
            )
        ),
        model_name(settings),
        improver,
        train,
        dev,
        fixtures,
        cases.parent / "cache",
        out,
        rounds,
        fmt=fmt,
        effort=effort,
    )
    typer.echo(f"wrote {out}")


def main() -> None:
    app()
