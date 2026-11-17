import assert from "node:assert/strict";
import { test } from "node:test";
import { beginLogin, pkceChallenge, validateCallback } from "../web/oauth.mjs";

const config = { authDomain: "https://example.auth.us-east-2.amazoncognito.com", clientId: "test-client",
  redirectUri: "http://localhost:8040/", scopes: ["openid", "test/recipes.read"] };

test("PKCE S256 matches the RFC 7636 example", async () => {
  assert.equal(await pkceChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
});
test("each login gets a fresh state/verifier and requests code plus S256", async () => {
  const first = await beginLogin(config, 1000), second = await beginLogin(config, 1000);
  assert.notEqual(first.transaction.state, second.transaction.state);
  assert.notEqual(first.transaction.verifier, second.transaction.verifier);
  assert.equal(first.url.searchParams.get("response_type"), "code");
  assert.equal(first.url.searchParams.get("code_challenge_method"), "S256");
  assert.equal(first.url.searchParams.get("redirect_uri"), config.redirectUri);
});
test("callback requires a matching unexpired, single-use transaction", async () => {
  const { transaction } = await beginLogin(config, 1000);
  const params = new URLSearchParams({ state: transaction.state, code: "test-code" });
  assert.equal(validateCallback(params, transaction, config.redirectUri, 2000).code, "test-code");
  assert.throws(() => validateCallback(params, null, config.redirectUri, 2000));
  assert.throws(() => validateCallback(new URLSearchParams({ code: "test" }), { ...transaction, state: null }, config.redirectUri, 2000));
  assert.throws(() => validateCallback(new URLSearchParams({ state: "wrong", code: "test" }), transaction, config.redirectUri, 2000));
  assert.throws(() => validateCallback(params, transaction, config.redirectUri, 602000));
  assert.throws(() => validateCallback(params, transaction, "https://another-host/", 2000));
  assert.throws(() => validateCallback(new URLSearchParams({ state: transaction.state, error: "access_denied" }), transaction, config.redirectUri, 2000));
});
