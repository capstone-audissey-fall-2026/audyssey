import asyncio
import zipfile
from importlib.resources import files
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, UploadFile
import httpx
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from audyssey import trace
from audyssey.contracts import (
    AddSource,
    Generate,
    Job,
    Render,
    Reseparate,
    parse_command,
)
from audyssey.graph import Context, analyze, handle_command
from audyssey.media import MediaError, check_upload
from audyssey.settings import Settings
from audyssey.store import JobStore
from audyssey.uploads import save_upload
from audyssey.tools import Tools, load_tools


def create_app(settings: Settings | None = None, tools: Tools | None = None) -> FastAPI:
    settings = settings or Settings()
    ctx = Context(tools or load_tools(settings), settings, JobStore(settings.work_dir))
    app = FastAPI()
    app.state.ctx = ctx
    locks: dict[str, Lock] = {}
    jobs: dict[str, Job] = {}
    app.state.locks, app.state.jobs = locks, jobs

    def load(job_id: str) -> Job:
        try:
            return ctx.store.load(job_id)
        except KeyError as exc:
            raise HTTPException(404, "job not found") from exc

    @app.post("/api/jobs", status_code=201)
    def upload(file: UploadFile) -> Job:
        with TemporaryDirectory() as tmp:
            limit = int(settings.max_upload_mb * 2**20)
            path = save_upload(file, Path(tmp) / "upload", limit)
            try:
                duration = check_upload(path, settings.max_duration_s)
            except MediaError as exc:
                raise HTTPException(400, str(exc)) from exc
            data = path.read_bytes()
        job, _ = ctx.store.create(file.filename or "video.mp4", data)
        job.duration = duration
        ctx.store.save(job)
        jobs[job.id] = job
        lock = locks.setdefault(job.id, Lock())
        lock.acquire()
        snapshot = job.model_copy(deep=True)

        # Upload only preprocesses; the user starts separation or generation.
        # Release the lock before the final state is saved, so a client that sees
        # new/failed can start at once.
        Thread(target=analyze, args=(job, ctx, lock.release, None), daemon=True).start()
        return snapshot

    @app.post("/api/jobs/{job_id}/start")
    def start(job_id: str, data: dict = Body(...)) -> Job:
        method = data.get("method")
        if method not in ("separate", "generate"):
            raise HTTPException(422, "method must be separate or generate")
        job = jobs.setdefault(job_id, load(job_id))
        if job.state != "new":
            raise HTTPException(409, "job has already started")
        if method == "separate" and job.silent:
            raise HTTPException(422, "silent videos only support generation")
        lock = locks.setdefault(job_id, Lock())
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "job is busy")
        job.state = "running"
        snapshot = ctx.store.save(job).model_copy(deep=True)
        Thread(
            target=analyze, args=(job, ctx, lock.release, method), daemon=True
        ).start()
        return snapshot

    @app.get("/api/jobs")
    def list_jobs() -> list[Job]:
        return ctx.store.list()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> Job:
        return load(job_id)

    @app.get("/api/jobs/{job_id}/events")
    async def events(job_id: str, request: Request) -> StreamingResponse:
        initial = load(job_id)

        async def stream():
            job = initial
            version = job.version
            yield f"data: {job.model_dump_json()}\n\n"
            # ponytail: polling store, push from save() if latency matters
            while not await request.is_disconnected():
                await asyncio.sleep(0.25)
                job = load(job_id)
                if job.version != version:
                    version = job.version
                    yield f"data: {job.model_dump_json()}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/jobs/{job_id}/commands")
    def command(job_id: str, data: dict = Body(...)) -> Job:
        snapshot = load(job_id)
        try:
            cmd = parse_command(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # Share the live job so edits made during analysis survive later saves.
        job = jobs.setdefault(job_id, snapshot)
        lock = locks.setdefault(job_id, Lock())
        execution = isinstance(cmd, (Reseparate, Generate, AddSource, Render))
        if execution and not lock.acquire(blocking=False):
            raise HTTPException(409, "job is busy")
        try:
            return handle_command(job, cmd, ctx).model_copy(deep=True)
        except KeyError as exc:
            raise HTTPException(404, "source not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            if execution:
                lock.release()

    @app.get("/api/jobs/{job_id}/files/{path:path}")
    def get_file(job_id: str, path: str) -> FileResponse:
        try:
            return FileResponse(ctx.store.resolve(job_id, path))
        except KeyError as exc:
            raise HTTPException(404, "file not found") from exc

    @app.get("/api/system")
    def system() -> list[dict]:
        """Servers in pipeline order, with what runs on each and whether it is up."""
        urls = {
            "separate": (settings.separator, settings.separator_url),
            "judge": (settings.filter, settings.filter_url),
            "ground": (settings.grounder, settings.grounding_url),
            "generate": (settings.generator, settings.generator_url),
        }
        lanes = trace.lanes(settings)
        for lane in lanes:
            lane["up"] = None
            remote = [
                urls[s][1] for s in lane["steps"] if urls.get(s, ("",))[0] == "remote"
            ]
            if lane["id"].startswith("llm:"):
                remote = [lane["id"].removeprefix("llm:")]
            if lane["id"] == "app":
                lane["up"] = True
            elif remote:
                url = remote[0] if "://" in remote[0] else f"http://{remote[0]}"
                try:
                    lane["up"] = httpx.get(f"{url}/health", timeout=1).is_success
                except httpx.HTTPError:
                    lane["up"] = False
        return lanes

    @app.get("/api/jobs/{job_id}/trace")
    def get_trace(job_id: str) -> list[dict]:
        load(job_id)
        return trace.read(ctx.store.dir(job_id))

    @app.get("/api/jobs/{job_id}/export")
    def export(job_id: str) -> Response:
        """Rendered video, mix and stems in one zip."""
        job = load(job_id)
        if job.outputs is None:
            raise HTTPException(409, "render the job first")
        directory = ctx.store.dir(job_id)
        paths = [job.outputs.video_mp4, job.outputs.mix_wav, *job.outputs.stems]
        with TemporaryDirectory() as tmp:
            archive = Path(tmp) / "export.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                for rel in paths:
                    stream.write(directory / rel, rel.removeprefix("out/"))
            data = archive.read_bytes()
        return Response(
            data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="audyssey-{job_id}.zip"'
            },
        )

    @app.get("/")
    def root() -> HTMLResponse:
        return HTMLResponse((files("audyssey.ui") / "index.html").read_text())

    @app.get("/dev")
    def dev() -> HTMLResponse:
        return HTMLResponse((files("audyssey.devui") / "index.html").read_text())

    return app
