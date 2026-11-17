"""Per-job record of every tool call: what went in, what came out, where it ran.

The demo UI reads it to show each model's inputs and outputs. Records go to
<job>/trace.jsonl; files a call sends or returns are kept under <job>/trace/<id>/.
"""

import inspect
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel

from audyssey.settings import LLMEndpoint, Settings

_lock = Lock()
_step: ContextVar[str] = ContextVar("trace_step", default="")
_call: ContextVar["Call | None"] = ContextVar("trace_call", default=None)


def set_step(key: str) -> None:
    """Name the pipeline step that the following tool calls belong to."""
    _step.set(key)


@dataclass
class Call:
    directory: Path
    tool: str
    server: str
    inputs: dict[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex[:10])
    step: str = field(default_factory=_step.get)
    started: float = field(default_factory=time.time)
    requests: list[dict[str, Any]] = field(default_factory=list)
    output: Any = None
    error: str | None = None

    def save(self, name: str, data: bytes) -> str:
        """Keep a file the call sent or received; returns its job-relative path."""
        path = self.directory / "trace" / self.id / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path.relative_to(self.directory))


def current() -> Call | None:
    return _call.get()


def describe(value: Any, directory: Path, call: Call | None = None) -> Any:
    """JSON-able view of a tool argument or result.

    Files inside the job become {"file": path}. With call set, they are copied into
    the call's folder first, so later retries that overwrite them keep this version.
    """
    if isinstance(value, Path):
        path = value.resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            return str(value)
        if call is not None:
            return {"file": call.save(path.name, path.read_bytes())}
        return {"file": str(path.relative_to(directory))}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [describe(item, directory, call) for item in value]
    if isinstance(value, dict):
        return {str(k): describe(v, directory, call) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


@contextmanager
def call(
    directory: Path, tool: str, server: str, inputs: dict[str, Any]
) -> Iterator[Call]:
    record = Call(directory, tool, server, inputs)
    token = _call.set(record)
    try:
        yield record
    except Exception as exc:
        record.error = str(exc)
        raise
    finally:
        _call.reset(token)
        line = {
            "id": record.id,
            "step": record.step,
            "tool": record.tool,
            "server": record.server,
            "started": record.started,
            "seconds": round(time.time() - record.started, 3),
            "inputs": record.inputs,
            "requests": record.requests,
            "output": record.output,
            "error": record.error,
        }
        with _lock, (directory / "trace.jsonl").open("a") as stream:
            stream.write(json.dumps(line) + "\n")


def read(directory: Path) -> list[dict[str, Any]]:
    path = directory / "trace.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _host(url: str) -> str:
    return urlparse(url).netloc or url


def _endpoint_lane(endpoint: LLMEndpoint) -> tuple[str, str, str]:
    if endpoint.api == "gemini":
        return "gemini", "Gemini API", endpoint.model
    host = _host(endpoint.base_url)
    name = "OpenAI API" if "openai.com" in host else f"vLLM ({host})"
    return f"llm:{host}", name, endpoint.model


def lanes(settings: Settings) -> list[dict[str, Any]]:
    """Where each step runs, grouped by server, in pipeline order."""
    found: dict[str, dict[str, Any]] = {}

    def put(key: str, name: str, detail: str, step: str) -> None:
        lane = found.setdefault(
            key, {"id": key, "name": name, "models": [], "steps": []}
        )
        if detail and detail not in lane["models"]:
            lane["models"].append(detail)
        lane["steps"].append(step)

    def tool(mode: str, url: str, model: str, *steps: str) -> None:
        for step in steps:
            if mode == "remote":
                put(f"tool:{_host(url)}", f"Tool server ({_host(url)})", model, step)
            elif mode == "real":
                put("app", "App server", model, step)
            else:
                put("app", "App server", "stub", step)

    put("app", "App server", "", "preprocess")
    if settings.planner == "real":
        put(*_endpoint_lane(settings.planner_endpoint()), "plan")
        put(*_endpoint_lane(settings.validator_endpoint()), "validate_plan")
    else:
        put("app", "App server", "stub", "plan")
        put("app", "App server", "stub", "validate_plan")
    if settings.visual_prompt:
        tool(settings.grounder, settings.grounding_url, settings.sam3_model, "ground")
    tool(
        settings.separator, settings.separator_url, settings.sam_audio_model, "separate"
    )
    tool(settings.filter, settings.filter_url, settings.sam_audio_judge_model, "judge")
    tool(
        settings.generator,
        settings.generator_url,
        settings.gen_model,
        "generate",
        "score",
    )
    put("app", "App server", "", "residual")
    put("app", "App server", "", "render")
    return list(found.values())


# Tool name -> lane step, so a call record can be placed on its lane.
TOOL_STEPS = {
    "plan": "plan",
    "validate_plan": "validate_plan",
    "separate": "separate",
    "judge": "judge",
    "locate": "ground",
    "mask_video": "ground",
    "generate": "generate",
    "score_generation": "score",
}


def wrap_tools(tools: Any, directory: Path, settings: Settings) -> Any:
    """Same Tools, with every call recorded under the job directory."""
    servers = {step: lane["name"] for lane in lanes(settings) for step in lane["steps"]}

    def wrap(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        params = list(inspect.signature(fn).parameters)

        def run(*args: Any) -> Any:
            inputs = {p: describe(a, directory) for p, a in zip(params, args)}
            server = servers.get(TOOL_STEPS.get(name, name), "App server")
            with call(directory, name, server, inputs) as record:
                result = fn(*args)
                record.output = describe(result, directory, record)
                return result

        return run

    return replace(
        tools, **{f.name: wrap(f.name, getattr(tools, f.name)) for f in fields(tools)}
    )


@contextmanager
def step(directory: Path, name: str, inputs: dict[str, Any]) -> Iterator[Call]:
    """Record an app-side step (preprocess, residual, render) like a tool call."""
    with call(directory, name, "App server", inputs) as record:
        yield record
