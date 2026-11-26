import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { job, plan, source, ssr } from "./helpers.mjs";

const request = {
  model: "Qwen3-VL-8B-Instruct",
  api: "openai",
  input: "frames",
  fps: 2,
  audio: false,
  purpose: "plan",
  attempt: 2,
  system: "You are a sound designer.",
  text: "Plan the sounds for this clip.",
  media: [
    { kind: "image", file: "trace/c1/frame_0.jpg", label: "Frame at 0.5 seconds" },
    { kind: "video", file: "trace/c1/clip.mp4", label: "Video from 1.0 to 2.0 seconds" },
    { kind: "audio", file: "trace/c1/a.wav", label: "Audio" },
  ],
  raw: '{"sources":[{"name":"dog"}]}',
  usage: { input_tokens: 120, output_tokens: 30, total_tokens: 150 },
};
const call = (over = {}) => ({ id: "c1", step: "plan", tool: "plan", server: "app", started: 1, seconds: 3.2, inputs: {}, requests: [request], output: [{ name: "dog", kind: "sfx", description: "barks", spans: [{ start: 1, end: 2 }] }], error: null, ...over });

async function load(context) {
  return (await ssr(context)).ssrLoadModule("/src/components/Inspector.tsx");
}
const props = { open: false, onClose() {}, step: "plan", job: job({ id: "J1" }), lane: { id: "app", name: "App server", models: ["gemini"], steps: ["plan"], up: true } };

test("Inspector shows frames, clips, prompt and response of a call", async (context) => {
  const { default: Inspector } = await load(context);
  const html = renderToStaticMarkup(createElement(Inspector, { ...props, calls: [call()] }));
  assert.match(html, /<img[^>]*src="\/api\/jobs\/J1\/files\/trace\/c1\/frame_0\.jpg"/);
  assert.match(html, /<video[^>]*src="\/api\/jobs\/J1\/files\/trace\/c1\/clip\.mp4"/);
  assert.match(html, /<audio[^>]*src="\/api\/jobs\/J1\/files\/trace\/c1\/a\.wav"/);
  assert.match(html, /Plan the sounds for this clip\./);
  assert.match(html, /You are a sound designer\./); // prompt
  assert.match(html, /Prompt/);
  assert.match(html, /Response/);
  assert.match(html, /&quot;name&quot;: &quot;dog&quot;/); // pretty-printed raw response
  assert.match(html, /120 \+ 30 tokens/);
  assert.match(html, /retry 2|attempt 2/i);
  assert.match(html, /barks/); // the output
  assert.match(html, /App server/);
});

test("Inspector shows a call error, and an empty state that tells running from nothing recorded", async (context) => {
  const { default: Inspector } = await load(context);
  const withError = renderToStaticMarkup(createElement(Inspector, { ...props, calls: [call({ requests: [], error: "boom: unreachable", output: null, inputs: { plan: { name: "dog" } } })] }));
  assert.match(withError, /boom: unreachable/);
  assert.match(renderToStaticMarkup(createElement(Inspector, { ...props, calls: [] })), /No calls recorded/);
  const running = job({ state: "running", steps: [{ key: "plan", status: "running", round: 1, max_rounds: 3, message: "" }] });
  assert.match(renderToStaticMarkup(createElement(Inspector, { ...props, job: running, calls: [] })), /Running/);
});

test("EdgePopover shows only what crossed the edge", async (context) => {
  const { EdgePopover } = await load(context);
  const j = job({ id: "J1" });
  const calls = [call({ tool: "validate_plan", step: "validate_plan", requests: [], inputs: { plans: [{ name: "dog", kind: "sfx", description: "barks", spans: [] }], extra: "ignored" }, output: [] })];
  const html = renderToStaticMarkup(createElement(EdgePopover, { edge: "edge:plan>validate_plan", job: j, calls, x: 100, y: 100, onClose() {} }));
  assert.match(html, /Plan → Check/);
  assert.match(html, /barks/);
  assert.doesNotMatch(html, /ignored/);
  const empty = renderToStaticMarkup(createElement(EdgePopover, { edge: "edge:plan>validate_plan", job: j, calls: [], x: 0, y: 0, onClose() {} }));
  assert.match(empty, /Nothing sent yet/);
});
