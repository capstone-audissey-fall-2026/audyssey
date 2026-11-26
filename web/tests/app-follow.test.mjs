import assert from "node:assert/strict";
import test from "node:test";
import { job, ssr } from "./helpers.mjs";

class FakeEventSource {
  static all = [];
  closed = false;
  constructor(url) {
    this.url = url;
    FakeEventSource.all.push(this);
  }
  close() {
    this.closed = true;
  }
}

async function controller(context, jobs = {}) {
  const server = await ssr(context);
  const { ApiError } = await server.ssrLoadModule("/src/api.ts");
  const { JobController } = await server.ssrLoadModule("/src/lib/useJob.ts");
  const realFetch = globalThis.fetch;
  globalThis.EventSource = FakeEventSource;
  FakeEventSource.all = [];
  globalThis.fetch = async (url) => {
    const id = String(url).split("/").pop();
    return new Response(JSON.stringify(jobs[id]), { status: jobs[id] ? 200 : 404 });
  };
  const ctl = new JobController();
  context.after(() => {
    ctl.dispose();
    globalThis.fetch = realFetch;
    delete globalThis.EventSource;
  });
  return { ctl, ApiError };
}

test("messages from another job or with a lower version are ignored", async (context) => {
  const { ctl } = await controller(context, { a: job({ id: "a", version: 3 }), b: job({ id: "b", version: 1 }) });
  await ctl.follow("a");
  assert.equal(ctl.job.version, 3);
  assert.equal(FakeEventSource.all[0].url, "/api/jobs/a/events");

  ctl.receive(job({ id: "b", version: 9 }));
  ctl.receive(job({ id: "a", version: 2 }));
  assert.equal(ctl.job.id, "a");
  assert.equal(ctl.job.version, 3);
  ctl.receive(job({ id: "a", version: 4 }));
  assert.equal(ctl.job.version, 4);
});

test("switching jobs closes the old stream and drops its late answers", async (context) => {
  const { ctl } = await controller(context, { a: job({ id: "a", version: 1 }), b: job({ id: "b", version: 1 }) });
  await ctl.follow("a");
  await ctl.follow("b");
  assert.equal(FakeEventSource.all[0].closed, true);
  assert.equal(ctl.job.id, "b");
  ctl.receive(job({ id: "a", version: 50 }));
  assert.equal(ctl.job.id, "b");
  assert.equal(ctl.error, null);
});

test("a failed open leaves no job and says so", async (context) => {
  const { ctl } = await controller(context, {});
  await ctl.follow("zzz");
  assert.equal(ctl.job, null);
  assert.equal(ctl.error, "HTTP 404");
});

test("run: one change at a time; a 409 says another change is running and clears busy", async (context) => {
  const { ctl, ApiError } = await controller(context, { a: job({ id: "a" }) });
  await ctl.follow("a");

  assert.equal(await ctl.run("Adding", async () => 7), 7);
  assert.equal(ctl.busy, null);

  const rejected = await ctl.run("Adding", async () => {
    throw new ApiError(409, "job is busy");
  });
  assert.equal(rejected, undefined);
  assert.equal(ctl.error, "Another change is still running.");
  assert.equal(ctl.busy, null);

  // A second run while one is in flight is not started.
  let release;
  let calls = 0;
  const first = ctl.run("Adding", () => new Promise((resolve) => ((calls += 1), (release = resolve))));
  assert.equal(ctl.busy, "Adding");
  assert.equal(ctl.error, null);
  assert.equal(await ctl.run("Other", async () => (calls += 1)), undefined);
  assert.equal(calls, 1);
  release("done");
  assert.equal(await first, "done");
  assert.equal(ctl.busy, null);
});
