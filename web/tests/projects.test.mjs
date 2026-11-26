import assert from "node:assert/strict";
import test from "node:test";
import { job, source, ssr } from "./helpers.mjs";

test("projectRow: short id, state, duration, method and track count", async (context) => {
  const { projectRow } = await (await ssr(context)).ssrLoadModule("/src/lib/projects.ts");
  const row = projectRow(job({ id: "abcdef123456", sources: [source("s1"), source("s2"), source("s3", { status: "skipped" })] }));
  assert.deepEqual(row, { id: "abcdef123456", label: "abcdef", detail: "ready · 7.1 s · separate · 2 tracks" });
  assert.equal(projectRow(job({ state: "new", method: null, sources: [] })).detail, "new · 7.1 s · 0 tracks");
  assert.match(projectRow(job({ method: "generate", sources: [source("s1")] })).detail, /generate · 1 track$/);
});
