import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ssr } from "./helpers.mjs";

test("GPU tools form: URL field and a password token field that is never prefilled", async (context) => {
  const { default: Form } = await (await ssr(context)).ssrLoadModule("/src/components/GpuToolsForm.tsx");
  const html = renderToStaticMarkup(createElement(Form, { open: false }));
  assert.match(html, /<h3>GPU tools<\/h3>/);
  assert.match(html, /Tools server URL/);
  assert.match(html, /<input[^>]*name="token"[^>]*type="password"|<input[^>]*type="password"[^>]*name="token"/);
  assert.match(html, /<input[^>]*name="token"[^>]*value=""/);
  assert.match(html, /role="status"/);
  assert.doesNotMatch(html, /role="alert"/);
});

test("api client saves the connection and sends a null token to keep it", async (context) => {
  const api = await (await ssr(context)).ssrLoadModule("/src/api.ts");
  const real = globalThis.fetch;
  context.after(() => (globalThis.fetch = real));
  let seen;
  globalThis.fetch = async (url, init) => ((seen = [url, init]), new Response(JSON.stringify({ tools_url: "http://gpu:8700", token_set: true, remote: {} }), { status: 200 }));
  await api.saveGpuTools("http://gpu:8700", null);
  assert.equal(seen[0], "/api/gpu-tools");
  assert.equal(seen[1].body, '{"tools_url":"http://gpu:8700","token":null}');
});

test("save failure hint: wait for the job on 409, check the URL otherwise", async (context) => {
  const server = await ssr(context);
  const { gpuToolsSaveNext } = await server.ssrLoadModule("/src/lib/errors.ts");
  const { ApiError } = await server.ssrLoadModule("/src/api.ts");
  assert.match(gpuToolsSaveNext(new ApiError(409, "a job is running")), /Wait for the running job/);
  assert.match(gpuToolsSaveNext(new ApiError(422, "tools_url must be an http(s) URL")), /Check the URL/);
  assert.match(gpuToolsSaveNext(new Error("network")), /Check the URL/);
});
