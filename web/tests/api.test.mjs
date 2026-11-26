import assert from "node:assert/strict";
import test from "node:test";
import { job, ssr } from "./helpers.mjs";

test("api client throws ApiError with the server detail", async (context) => {
  const api = await (await ssr(context)).ssrLoadModule("/src/api.ts");
  const real = globalThis.fetch;
  context.after(() => (globalThis.fetch = real));
  const reply = (status, body) => async () => new Response(JSON.stringify(body), { status });

  globalThis.fetch = reply(400, { detail: "video is 40.0s; maximum is 30s" });
  await assert.rejects(api.uploadVideo(new Blob(["x"])), (e) => {
    assert.ok(e instanceof api.ApiError);
    assert.equal(e.status, 400);
    assert.equal(e.detail, "video is 40.0s; maximum is 30s");
    return true;
  });
  globalThis.fetch = reply(422, { detail: [{ msg: "bad gain" }, { msg: "bad id" }] });
  await assert.rejects(api.sendCommand("j", { type: "render", include_residual_stem: false }), (e) => e.detail === "bad gain bad id");
  globalThis.fetch = reply(409, { detail: "job is busy" });
  await assert.rejects(api.sendCommand("j", { type: "render", include_residual_stem: false }), (e) => e.status === 409);

  let seen;
  globalThis.fetch = async (url, init) => ((seen = [url, init]), new Response(JSON.stringify(job()), { status: 200 }));
  assert.equal((await api.startJob("j1", "generate")).id, "abc123def");
  assert.equal(seen[0], "/api/jobs/j1/start");
  assert.equal(seen[1].body, '{"method":"generate"}');
  assert.equal(api.fileUrl("j1", "out/a b.wav"), "/api/jobs/j1/files/out/a%20b.wav");
  assert.equal(api.exportUrl("j1"), "/api/jobs/j1/export");
});

test("errorDetail reads an ApiError", async (context) => {
  const server = await ssr(context);
  const { ApiError } = await server.ssrLoadModule("/src/api.ts");
  const { errorDetail } = await server.ssrLoadModule("/src/lib/errors.ts");
  assert.equal(errorDetail(new ApiError(409, "job is busy")), "job is busy");
});
