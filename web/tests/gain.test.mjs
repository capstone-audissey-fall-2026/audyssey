import assert from "node:assert/strict";
import test from "node:test";
import { ssr } from "./helpers.mjs";

test("gain helpers: 0..200 % maps to gain 0..2", async (context) => {
  const g = await (await ssr(context)).ssrLoadModule("/src/lib/gain.ts");
  assert.equal(g.GAIN_MAX_PERCENT, 200);
  assert.equal(g.gainToPercent(undefined), 100);
  assert.equal(g.gainToPercent(1.35), 135);
  assert.equal(g.percentToGain(450), 2);
  assert.equal(g.percentToGain(-5), 0);
  assert.equal(g.percentToGain(50), 0.5);
});
