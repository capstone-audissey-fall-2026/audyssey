import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import InMemorySaver

from audyssey import graph
from audyssey.settings import Settings
from audyssey.store import JobStore
from audyssey.tools import load_tools
from tests.audyssey_media import make_video


class GraphFactoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.video = make_video(self.root / "clip.mp4")
        settings = Settings(work_dir=self.root / "jobs")
        self.ctx = graph.Context(
            load_tools(settings), settings, JobStore(settings.work_dir)
        )
        self.job, self.directory = self.ctx.store.create(
            "clip.mp4", self.video.read_bytes()
        )

    def test_build_graph_exposes_topology_without_executing_tools(self):
        plan = Mock(wraps=self.ctx.tools.plan)
        self.ctx.tools = replace(self.ctx.tools, plan=plan)
        pipeline = graph.build_graph(self.ctx)
        diagram = pipeline.get_graph().draw_mermaid()
        for name in ("preprocess", "plan", "validate", "separate", "residual"):
            self.assertIn(name, diagram)
        plan.assert_not_called()
        self.assertFalse((self.directory / "audio.wav").exists())

    def test_studio_entry_exports_the_shared_graph(self):
        project = Path(__file__).resolve().parents[1]
        config = json.loads((project / "langgraph.json").read_text(encoding="utf-8"))
        path, name = config["graphs"]["audyssey"].split(":")
        pipeline = graph.build_graph(self.ctx)
        with patch.object(graph, "build_graph", return_value=pipeline) as build:
            namespace = runpy.run_path(str(project / path))
        self.assertIs(namespace[name], pipeline)
        build.assert_called_once_with()

    def test_graph_runs_from_a_stored_job_id(self):
        result = graph.build_graph(self.ctx).invoke({"job_id": self.job.id})
        job = result["job"]
        self.assertEqual(job.state, "ready", job.error)
        self.assertEqual([source.status for source in job.sources], ["done"] * 3)
        self.assertEqual(self.ctx.store.load(job.id).state, "ready")
        self.assertEqual(result["round"], 2)

    def test_graph_accepts_json_job_input(self):
        result = graph.build_graph(self.ctx).invoke(
            {"job": self.job.model_dump(mode="json")}
        )
        self.assertEqual(result["job"].state, "ready")

    def test_one_graph_can_run_different_jobs_concurrently(self):
        other, _ = self.ctx.store.create("other.mp4", self.video.read_bytes())
        pipeline = graph.build_graph(self.ctx)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    pipeline.invoke,
                    [
                        {"job_id": self.job.id},
                        {"job_id": other.id},
                    ],
                )
            )
        self.assertEqual(
            [result["job"].id for result in results], [self.job.id, other.id]
        )
        for result in results:
            job = result["job"]
            self.assertEqual(job.state, "ready", job.error)
            self.assertTrue((self.ctx.store.dir(job.id) / job.residual.path).is_file())

    def test_checkpointed_thread_can_select_a_new_job_id(self):
        other, _ = self.ctx.store.create("other.mp4", self.video.read_bytes())
        pipeline = graph.build_graph(self.ctx)
        pipeline.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": "studio-test"}}
        pipeline.invoke({"job_id": self.job.id}, config)
        result = pipeline.invoke({"job_id": other.id}, config)
        self.assertEqual(result["job"].id, other.id)
        self.assertEqual(result["job"].state, "ready")

    def test_concurrent_jobs_do_not_share_planning_intent(self):
        from threading import Barrier
        from audyssey.contracts import SourcePlan
        from audyssey.tools.planning import current_request

        silent_video = make_video(self.root / "silent.mp4", audio=False)
        other, _ = self.ctx.store.create("silent.mp4", silent_video.read_bytes())
        barrier = Barrier(2)
        observed = {}

        def plan(video, audio, duration, feedback):
            before = current_request()
            barrier.wait(timeout=10)
            observed[video.parent.name] = (before, current_request())
            return [SourcePlan(name="effect", kind="sfx", description="an effect")]

        self.ctx.tools = replace(self.ctx.tools, plan=plan, validate_plan=lambda *args: [])
        pipeline = graph.build_graph(self.ctx)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(pipeline.invoke, [
                {"job_id": self.job.id, "method": "separate"},
                {"job_id": other.id, "method": "generate"},
            ]))
        self.assertTrue(all(r["job"].state == "ready" for r in results))
        for job_id, purpose, available in [(self.job.id, "separate", True), (other.id, "generate", False)]:
            before, after = observed[job_id]
            self.assertEqual((before.purpose, before.audio_available), (purpose, available))
            self.assertEqual(before, after)
        self.assertEqual(current_request().purpose, "separate")

    def test_preprocess_then_start_reuses_prepared_audio(self):
        pipeline = graph.build_graph(self.ctx)
        prepared = pipeline.invoke({"job_id": self.job.id, "method": None})["job"]
        self.assertEqual(prepared.state, "new")
        self.assertEqual(prepared.sources, [])
        with patch.object(
            graph, "extract_audio", side_effect=AssertionError("already prepared")
        ):
            result = pipeline.invoke({"job_id": self.job.id, "method": "separate"})
        self.assertEqual(result["job"].state, "ready", result["job"].error)

    def test_studio_can_switch_an_existing_job_between_methods(self):
        pipeline = graph.build_graph(self.ctx)
        pipeline.invoke({"job_id": self.job.id, "method": "separate"})
        generated = pipeline.invoke({"job_id": self.job.id, "method": "generate"})[
            "job"
        ]
        self.assertTrue(
            all(source.origin == "generated" for source in generated.sources)
        )
        self.assertEqual(generated.sources[0].status, "skipped")
        separated = pipeline.invoke({"job_id": self.job.id, "method": "separate"})[
            "job"
        ]
        self.assertTrue(
            all(source.origin == "separated" for source in separated.sources)
        )
        self.assertTrue(all(source.status == "done" for source in separated.sources))

    def test_direct_graph_failure_is_saved(self):
        self.ctx.tools = replace(
            self.ctx.tools, plan=Mock(side_effect=RuntimeError("planner unavailable"))
        )
        with self.assertRaisesRegex(RuntimeError, "planner unavailable"):
            graph.build_graph(self.ctx).invoke({"job_id": self.job.id})
        job = self.ctx.store.load(self.job.id)
        self.assertEqual((job.state, job.error), ("failed", "planner unavailable"))
        self.assertEqual(job.steps[-1].key, "plan")
        self.assertEqual(job.steps[-1].status, "failed")

    def test_analyze_preserves_live_job_and_releases_before_final_save(self):
        finish = Mock()
        save = self.ctx.store.save

        def save_after_release(job):
            if job.state in {"new", "ready", "failed"}:
                finish.assert_called_once_with()
            return save(job)

        with patch.object(self.ctx.store, "save", side_effect=save_after_release):
            result = graph.analyze(self.job, self.ctx, on_finish=finish)
        self.assertIs(result, self.job)
        self.assertEqual(result.state, "ready")
        finish.assert_called_once_with()

    def test_analyze_releases_once_after_failure(self):
        finish = Mock()
        self.ctx.tools = replace(
            self.ctx.tools, plan=Mock(side_effect=RuntimeError("unavailable"))
        )
        job = graph.analyze(self.job, self.ctx, on_finish=finish)
        self.assertEqual(job.state, "failed")
        finish.assert_called_once_with()

    def test_analyze_handles_failure_before_a_node_starts(self):
        finish = Mock()
        with patch.object(
            graph, "build_graph", side_effect=RuntimeError("cannot compile")
        ):
            job = graph.analyze(self.job, self.ctx, on_finish=finish)
        self.assertEqual((job.state, job.error), ("failed", "cannot compile"))
        self.assertEqual(self.ctx.store.load(job.id).state, "failed")
        finish.assert_called_once_with()


import json
import runpy
