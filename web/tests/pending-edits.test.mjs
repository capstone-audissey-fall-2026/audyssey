import assert from "node:assert/strict";
import test from "node:test";
import { ssr } from "./helpers.mjs";

test("PendingEdits keeps one span draft per source", async (context) => {
  const { PendingEdits } = await (await ssr(context)).ssrLoadModule("/src/lib/pendingEdits.ts");
  const edits = new PendingEdits();
  assert.equal(edits.get("s1"), null);
  assert.deepEqual(edits.dirty(), []);
  edits.set("s1", [{ start: 1, end: 2 }]);
  edits.set("s2", [{ start: 0, end: 1 }]);
  assert.deepEqual(edits.get("s1"), [{ start: 1, end: 2 }]);
  assert.deepEqual(edits.dirty(), ["s1", "s2"]);
  edits.discard("s1");
  assert.deepEqual(edits.dirty(), ["s2"]);
  edits.discard();
  assert.deepEqual(edits.dirty(), []);
});

test("span list helpers: the last span cannot be removed, short drags draw nothing", async (context) => {
  const { drawSpan, removeSpan, sortSpans } = await (await ssr(context)).ssrLoadModule("/src/lib/span.ts");
  const one = [{ start: 1, end: 2 }];
  assert.equal(removeSpan(one, 0), one);
  assert.deepEqual(removeSpan([{ start: 0, end: 1 }, { start: 2, end: 3 }], 0), [{ start: 2, end: 3 }]);
  assert.equal(drawSpan(one, 3, 3.05, 10), one);
  assert.deepEqual(drawSpan(one, 4, 3, 10), [...one, { start: 3, end: 4 }]);
  assert.deepEqual(drawSpan(one, -2, 50, 10), [...one, { start: 0, end: 10 }]);
  assert.deepEqual(sortSpans([{ start: 5, end: 6 }, { start: 1, end: 2 }]), [{ start: 1, end: 2 }, { start: 5, end: 6 }]);
});
