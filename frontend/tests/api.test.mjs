import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Exercise the actual TypeScript transport without another test dependency or live APIs.
const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { api, setCsrfToken, ApiError } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
globalThis.window = new EventTarget();

test("publishing uses session credentials and CSRF, never the old shared token", async (t) => {
  setCsrfToken("session-bound-csrf");
  t.mock.method(globalThis, "fetch", async (path, options) => {
    assert.equal(path, "/api/reviews/123/publish");
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    assert.equal(options.headers["X-MergeScope-CSRF"], "session-bound-csrf");
    assert.equal(options.headers["X-MergeScope-Publish-Token"], undefined);
    assert.deepEqual(JSON.parse(options.body), { confirm: true });
    return Response.json({ status: "published" });
  });
  assert.equal((await api.publishReview("123")).status, "published");
});

test("file uploads retain browser multipart boundaries and send CSRF", async (t) => {
  setCsrfToken("csrf");
  t.mock.method(globalThis, "fetch", async (_, options) => {
    assert.ok(options.body instanceof FormData);
    assert.equal(options.headers["Content-Type"], undefined);
    assert.equal(options.headers["X-MergeScope-CSRF"], "csrf");
    return Response.json({ id: "document" });
  });
  await api.uploadDocument(new File(["test"], "rules.md"));
});

test("an expired protected request emits the private-workspace teardown event", async (t) => {
  let expired = 0;
  const listener = () => { expired++; };
  window.addEventListener("mergescope:expired", listener);
  t.after(() => window.removeEventListener("mergescope:expired", listener));
  t.mock.method(globalThis, "fetch", async () => Response.json({ detail: "Sign in again" }, { status: 401 }));
  await assert.rejects(api.reviews(), (error) => error instanceof ApiError && error.status === 401);
  assert.equal(expired, 1);
});

test("initial signed-out session check does not trigger an expiry loop", async (t) => {
  let expired = false;
  const listener = () => { expired = true; };
  window.addEventListener("mergescope:expired", listener);
  t.after(() => window.removeEventListener("mergescope:expired", listener));
  t.mock.method(globalThis, "fetch", async () => Response.json({ detail: "Sign in" }, { status: 401 }));
  await assert.rejects(api.me(), ApiError);
  assert.equal(expired, false);
});

test("logout supports no-content responses and token clearing", async (t) => {
  setCsrfToken("");
  t.mock.method(globalThis, "fetch", async (_, options) => {
    assert.equal(options.method, "POST");
    assert.equal(options.headers["X-MergeScope-CSRF"], "");
    return new Response(null, { status: 204 });
  });
  assert.equal(await api.logout(), undefined);
});
