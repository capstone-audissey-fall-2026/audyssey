import assert from "node:assert/strict";
import test from "node:test";
import { ssr } from "./helpers.mjs";

test("selection helpers", async (context) => {
  const s = await (await ssr(context)).ssrLoadModule("/src/lib/selection.ts");

  assert.deepEqual(s.statusView({ status: "done", origin: "separated" }, false), { label: "Done", tone: "ok" });
  assert.deepEqual(s.statusView({ status: "running", origin: "separated" }, true), { label: "Separating…", tone: "run" });
  assert.deepEqual(s.statusView({ status: "running", origin: "generated" }, true), { label: "Generating…", tone: "run" });
  assert.deepEqual(s.statusView({ status: "failed", origin: "generated" }, false), { label: "Failed", tone: "err" });
  assert.deepEqual(s.statusView({ status: "pending", origin: "separated" }, true), { label: "Queued", tone: "wait" });
  assert.deepEqual(s.statusView({ status: "pending", origin: "separated" }, false), { label: null, tone: null });

  assert.equal(s.reconcileSelection(null, []), null);
  assert.equal(s.reconcileSelection(null, ["a", "b"]), "a");
  assert.equal(s.reconcileSelection("b", ["a", "b"]), "b");
  assert.equal(s.reconcileSelection("gone", ["a", "b"]), "a");
  assert.equal(s.reconcileSelection("gone", []), "gone");

  assert.equal(s.objectColor(0), "#4cc9f0");
  assert.equal(s.objectColor(8), "#4cc9f0");
  assert.equal(s.objectColor(-1), s.NONE_COLOR);

  assert.equal(s.soloToggleAction({ previewPlaying: false, videoPlaying: false, soloTrackId: "a" }), null);
  assert.equal(s.soloToggleAction({ previewPlaying: false, videoPlaying: true, soloTrackId: "a" }), "play-solo");
  assert.equal(s.soloToggleAction({ previewPlaying: true, videoPlaying: true, soloTrackId: null }), "play-mix");
  assert.equal(s.soloToggleAction({ previewPlaying: false, videoPlaying: true, soloTrackId: null }), null);
});
