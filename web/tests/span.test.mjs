import assert from "node:assert/strict";
import test from "node:test";
import { ssr } from "./helpers.mjs";

test("span helpers work in seconds", async (context) => {
  const { MIN_SPAN, clampSpan, moveSpan, resizeSpan } = await (await ssr(context)).ssrLoadModule("/src/lib/span.ts");
  assert.equal(MIN_SPAN, 0.1);
  // Moving past the end keeps the length and stops at the duration.
  assert.deepEqual(moveSpan({ start: 1, end: 2 }, 10, 5), { start: 4, end: 5 });
  assert.deepEqual(moveSpan({ start: 1, end: 2 }, -10, 5), { start: 0, end: 1 });
  // Resizing below 0.1 s keeps 0.1 s.
  const small = resizeSpan({ start: 1, end: 2 }, "end", -5, 10);
  assert.equal(small.start, 1);
  assert.ok(Math.abs(small.end - 1.1) < 1e-9);
  const left = resizeSpan({ start: 1, end: 2 }, "start", 5, 10);
  assert.equal(left.end, 2);
  assert.ok(Math.abs(left.start - 1.9) < 1e-9);
  assert.deepEqual(resizeSpan({ start: 1, end: 2 }, "end", 50, 5), { start: 1, end: 5 });
  // Rounding must never push a moved span past the end (the server rejects end > duration).
  for (let i = 0; i < 20000; i++) {
    const duration = 1 + Math.random() * 30, length = 0.1 + Math.random() * 3;
    const moved = moveSpan({ start: 0.2, end: 0.2 + length }, 1000, duration);
    assert.ok(moved.end <= duration, `${moved.end} > ${duration}`);
  }
  assert.deepEqual(clampSpan({ start: -1, end: 99 }, 5), { start: 0, end: 5 });
});
