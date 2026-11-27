import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { job, source, ssr } from "./helpers.mjs";

const noop = () => {};
const topProps = { busy: null, error: null, method: "separate", onMethodChange: noop, onOpen: noop, onStart: noop, onExport: noop };

test("TopBar: silent job in state new cannot separate; a started job shows the method as a badge", async (context) => {
  const { default: TopBar } = await (await ssr(context)).ssrLoadModule("/src/components/TopBar.tsx");
  const render = (props) => renderToStaticMarkup(createElement(TopBar, { ...topProps, ...props }));

  const silent = render({ job: job({ silent: true, state: "new", method: null }), method: "generate" });
  assert.match(silent, /Silent video/);
  assert.match(silent, /<button[^>]*role="radio"[^>]*disabled=""[^>]*aria-describedby="no-audio-why"[^>]*>Separate</);
  assert.match(silent, /<span class="mode-why" id="no-audio-why">No original audio to separate\.<\/span>/);
  assert.match(silent, /<button[^>]*class="btn primary"[^>]*>Generate audio</);

  const fresh = render({ job: job({ state: "new", method: null }) });
  assert.match(fresh, /Original audio/);
  assert.match(fresh, /role="radiogroup"/);
  assert.match(fresh, /role="radio"[^>]*aria-checked="true"[^>]*>Separate</);
  assert.match(fresh, /Choose Separate or Generate to start\./);
  assert.doesNotMatch(fresh, /No original audio/);

  const ready = render({ job: job({ state: "ready", sources: [source("s1")] }) });
  assert.doesNotMatch(ready, /role="radio"/);
  assert.match(ready, /<span class="in-badge">Separate<\/span>/);
  assert.doesNotMatch(ready, /btn primary/);
  assert.match(ready, />Export</);
  assert.doesNotMatch(ready, /<button[^>]*disabled[^>]*>Export</);

  const running = render({ job: job({ state: "running", steps: [] }) });
  assert.match(running, /<button[^>]*disabled=""[^>]*>Export</);
  const busy = render({ job: job({ state: "new", method: null }), busy: "start" });
  assert.match(busy, /<button[^>]*disabled=""[^>]*class="btn primary"|<button[^>]*class="btn primary"[^>]*disabled=""/);
  assert.match(busy, /role="status"/);

  assert.match(render({ job: job({ state: "new", method: null }), error: "Another change is still running." }), /Another change is still running\./);
  assert.match(render({ job: null }), /Open a video to start\./);
  assert.match(render({ job: null }), />Open video</);
});

test("OpenVideoDialog shows the upload error next to the file input and lists recent projects", async (context) => {
  const { default: Dialog } = await (await ssr(context)).ssrLoadModule("/src/components/OpenVideoDialog.tsx");
  const html = renderToStaticMarkup(
    createElement(Dialog, {
      open: false,
      onClose: noop,
      onUpload: noop,
      uploading: false,
      uploadError: "video is 40.0s; maximum is 30s",
      projects: [job({ id: "abcdef123456" }), job({ id: "zzzzzz999", state: "new", method: null })],
      onOpenJob: noop,
    }),
  );
  assert.match(html, /<dialog/);
  assert.match(html, /type="file"/);
  assert.match(html, /<p class="err"[^>]*role="alert">[\s\S]*video is 40\.0s; maximum is 30s/);
  assert.match(html, /abcdef/);
  assert.match(html, /ready · 7\.1 s · separate · 0 tracks/);
  const empty = renderToStaticMarkup(createElement(Dialog, { open: false, onClose: noop, onUpload: noop, uploading: false, uploadError: null, projects: [], onOpenJob: noop }));
  assert.doesNotMatch(empty, /role="alert"/);
  assert.match(empty, /No projects yet/);
});
