import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { job, plan, source, ssr } from "./helpers.mjs";

function find(node, predicate, out = []) {
  if (Array.isArray(node)) node.forEach((n) => find(n, predicate, out));
  else if (node && typeof node === "object" && node.props) {
    if (predicate(node)) out.push(node);
    find(node.props.children, predicate, out);
  }
  return out;
}

test("PlanPanel lists sources, plan issues and skipped sources; a span seeks", async (context) => {
  const { default: PlanPanel } = await (await ssr(context)).ssrLoadModule("/src/components/PlanPanel.tsx");
  const j = job({
    sources: [
      source("s1", { plan: plan("dog", [{ start: 1, end: 2 }, { start: 5, end: 6.5 }]) }),
      source("s2", { plan: plan("hum", [{ start: 0, end: 3 }], "ambience"), status: "skipped" }),
    ],
    plan_issues: [{ source_name: "hum", kind: "span", message: "span is longer than the video" }],
  });
  const html = renderToStaticMarkup(createElement(PlanPanel, { job: j, onSeek() {} }));
  assert.match(html, /dog sound/);
  assert.match(html, /1\.0–2\.0 s/);
  assert.match(html, /5\.0–6\.5 s/);
  assert.match(html, /span is longer than the video/);
  assert.match(html, /Skipped by the plan check/);
  assert.match(html, /hum/);

  const seen = [];
  const tree = PlanPanel({ job: j, onSeek: (t) => seen.push(t) });
  const buttons = find(tree, (n) => n.type === "button" && n.props["data-seek"] !== undefined);
  assert.equal(buttons.length, 2);
  buttons[1].props.onClick();
  assert.deepEqual(seen, [5]);

  const clean = renderToStaticMarkup(createElement(PlanPanel, { job: job({ sources: [source("s1")] }), onSeek() {} }));
  assert.doesNotMatch(clean, /Skipped by the plan check/);
  assert.doesNotMatch(clean, /Plan issues/);
});
