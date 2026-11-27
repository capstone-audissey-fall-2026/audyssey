import assert from "node:assert/strict";
import test from "node:test";
import { job, source, ssr } from "./helpers.mjs";

const step = (key, status, over = {}) => ({ key, status, round: 0, max_rounds: 0, message: "", ...over });

test("statusLine describes the job in one line", async (context) => {
  const { statusLine } = await (await ssr(context)).ssrLoadModule("/src/lib/status.ts");

  assert.deepEqual(statusLine(null, null), { tone: "idle", text: "Open a video to start.", progress: null });
  assert.deepEqual(statusLine(job({ state: "new", method: null }), null), {
    tone: "idle",
    text: "Choose Separate or Generate to start.",
    progress: null,
  });

  const three = [source("s1"), source("s2"), source("s3")];
  const running = statusLine(
    job({ state: "running", sources: three, steps: [step("separate:s1", "done"), step("separate:s2", "running")] }),
    null,
  );
  assert.equal(running.tone, "run");
  assert.equal(running.text, "Separating 2 of 3");
  assert.ok(Math.abs(running.progress - 1 / 3) < 0.01);

  const planning = statusLine(job({ state: "running", steps: [step("plan", "running", { round: 2, max_rounds: 3 })] }), null);
  assert.equal(planning.text, "Planning sounds (round 2)");
  assert.equal(planning.progress, null);
  assert.equal(statusLine(job({ state: "running", steps: [] }), null).text, "Working…");

  const failed = statusLine(job({ state: "failed", error: "separator unreachable" }), null);
  assert.deepEqual([failed.tone, failed.text], ["fail", "separator unreachable"]);

  const done = statusLine(job({ sources: [...three, source("s4", { status: "skipped" })] }), null);
  assert.deepEqual([done.tone, done.text], ["done", "Done. 3 tracks ready to play."]);
  assert.equal(statusLine(job({ sources: [source("s1")] }), null).text, "Done. 1 track ready to play.");

  // A change in progress reports its running step; with none running it says Working.
  const adding = statusLine(job({ sources: three, steps: [step("separate:s4", "running")] }), "Adding track");
  assert.deepEqual([adding.tone, adding.text], ["run", "Separating 1 of 3"]);
  assert.equal(statusLine(job(), "Adding track").text, "Working…");
  assert.deepEqual(statusLine(job(), "export"), { tone: "run", text: "Exporting…", progress: null });
});
