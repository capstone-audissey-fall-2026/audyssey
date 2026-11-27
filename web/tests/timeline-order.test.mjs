import assert from "node:assert/strict";
import test from "node:test";
import { job, plan, source, ssr } from "./helpers.mjs";
import { render, timelineProps } from "./timeline-helpers.mjs";

test("lanes follow the row order and the residual lane comes last", async (context) => {
  const server = await ssr(context);
  const { default: Timeline } = await server.ssrLoadModule("/src/components/Timeline.tsx");
  const { jobToView } = await server.ssrLoadModule("/src/lib/adapter.ts");
  const view = jobToView(
    job({
      sources: [
        source("s1", { plan: plan("alpha") }),
        source("s2", { plan: plan("beta") }),
        source("s3", { plan: plan("gamma (generated)"), origin: "generated", replaces: "s1" }),
        source("s4", { plan: plan("skipped one"), status: "skipped" }),
      ],
    }),
  );
  const html = render(Timeline, timelineProps(view));
  const at = (text) => html.indexOf(text);
  assert.ok(at("alpha") > 0 && at("alpha") < at("gamma (generated)"));
  assert.ok(at("gamma (generated)") < at("beta"));
  assert.ok(at("beta") < at("Rest of the original audio"));
  assert.equal(at("skipped one"), -1);
  assert.equal((html.match(/class="lane[ "]/g) ?? []).length, 5); // ruler + 3 sources + residual
});
