import assert from "node:assert/strict";
import test from "node:test";
import { ssr } from "./helpers.mjs";

test("peaksDb maps -60..0 dBFS to 0..1", async (context) => {
  const { peaksDb } = await (await ssr(context)).ssrLoadModule("/src/lib/waveform.ts");
  const sine = Float32Array.from({ length: 4000 }, (_, i) => Math.sin((2 * Math.PI * i * 7) / 100));
  const loud = peaksDb(sine, 4);
  assert.equal(loud.length, 4);
  for (const v of loud) assert.ok(v > 0.99 && v <= 1, `full scale ${v}`);
  const quiet = peaksDb(new Float32Array(100).fill(0.001), 2); // -60 dBFS
  for (const v of quiet) assert.ok(Math.abs(v) < 1e-6, `-60 dB ${v}`);
  const half = peaksDb(new Float32Array(100).fill(0.0316228), 1); // -30 dBFS
  assert.ok(Math.abs(half[0] - 0.5) < 0.01);
  assert.deepEqual([...peaksDb(new Float32Array(100), 5)], [0, 0, 0, 0, 0]);
  assert.equal(peaksDb(new Float32Array(3), 8).length, 8);
});
