import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("App renders the Audyssey heading", async (context) => {
  const server = await createServer({
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
    server: { middlewareMode: true },
  });
  context.after(() => server.close());
  const { default: App } = await server.ssrLoadModule("/src/App.tsx");
  assert.match(renderToStaticMarkup(createElement(App)), /<h1>Audyssey<\/h1>/);
});
