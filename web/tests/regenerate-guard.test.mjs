import assert from "node:assert/strict";
import test from "node:test";
import { job, ssr } from "./helpers.mjs";

test("changes are blocked while the job or a command runs", async (context) => {
  const { regenerateBlockedReason } = await (await ssr(context)).ssrLoadModule("/src/lib/trackActions.ts");
  const why = "Another change is still running.";
  assert.equal(regenerateBlockedReason(job({ state: "ready" }), null), null);
  assert.equal(regenerateBlockedReason(job({ state: "running" }), null), why);
  assert.equal(regenerateBlockedReason(job({ state: "ready" }), "Adding track"), why);
  assert.equal(regenerateBlockedReason(job({ state: "new", method: null }), null), "Choose Separate or Generate first.");
  assert.equal(regenerateBlockedReason(job({ state: "failed" }), null), "The job failed; upload the video again.");
});
