import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ssr } from "./helpers.mjs";

const props = {
  videoSrc: "/api/jobs/j/files/input.mp4",
  duration: 7.1,
  time: 1.2,
  isPlaying: false,
  onTogglePlay() {},
  onSeek() {},
  boxes: [],
  highlight: null,
  videoRef: { current: null },
};

test("Stage shows the time readout, a seconds slider and the highlight chip", async (context) => {
  const { default: Stage } = await (await ssr(context)).ssrLoadModule("/src/components/Stage.tsx");
  const html = renderToStaticMarkup(createElement(Stage, { ...props, highlight: { text: "Highlighting Dog", color: "#4cc9f0" } }));
  assert.match(html, /1\.20 s \/ 7\.10 s/);
  assert.match(html, /Highlighting Dog/);
  assert.match(html, /<input[^>]*aria-label="Position"[^>]*max="7.1"|<input[^>]*max="7.1"[^>]*aria-label="Position"/);
  assert.match(html, /step="0.01"/);
  assert.match(html, /aria-label="Play video"/);
  assert.match(renderToStaticMarkup(createElement(Stage, { ...props, isPlaying: true })), /aria-label="Pause video"/);

  const none = renderToStaticMarkup(createElement(Stage, { ...props, highlight: { text: "Rain has no on-screen location", color: null } }));
  assert.match(none, /Rain has no on-screen location/);
  assert.match(none, /sw sw-none/);
  assert.doesNotMatch(renderToStaticMarkup(createElement(Stage, props)), /class="chip"/);
});

test("HighlightOverlay places each box as a percentage of the picture", async (context) => {
  const { default: Overlay } = await (await ssr(context)).ssrLoadModule("/src/components/HighlightOverlay.tsx");
  const html = renderToStaticMarkup(
    createElement(Overlay, { videoRef: { current: null }, boxes: [{ id: "s1", box: [0.1, 0.2, 0.5, 0.6], color: "#4cc9f0" }] }),
  );
  assert.match(html, /left:10%/);
  assert.match(html, /top:20%/);
  assert.match(html, /width:40%/);
  assert.match(html, /height:40%/);
  assert.match(html, /#4cc9f0/);
});
