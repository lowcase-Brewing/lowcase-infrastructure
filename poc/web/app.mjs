import { beginLogin, validateCallback } from "./oauth.mjs";

const $ = (id) => document.getElementById(id);
const TRANSACTION_KEY = "lowcase-poc-login";
let config;
let accessToken = null;
let expiresAt = 0;

function show(message, failed = false) {
  $("result").textContent = typeof message === "string" ? message : JSON.stringify(message, null, 2);
  $("result").classList.toggle("error", failed);
}

async function checkedJson(response) {
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || result.error_description || result.message || `Request failed (${response.status}).`);
  return result;
}

async function api(method, body) {
  if (!accessToken || Date.now() >= expiresAt) throw new Error("Sign in first. This test harness asks you to sign in again when the token expires.");
  const id = $("recipe-id").value.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(id)) throw new Error("Enter a valid recipe ID.");
  const result = await checkedJson(await fetch(`${config.apiBaseUrl}/recipes/${encodeURIComponent(id)}`, {
    method,
    headers: { Authorization: `Bearer ${accessToken}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
    cache: "no-store",
    referrerPolicy: "no-referrer",
  }));
  show({ status: method === "PUT" ? "Saved to your AWS POC user" : "Loaded from your AWS POC user", ...result });
  if (method === "GET") $("recipe-json").value = JSON.stringify({ schemaVersion: result.schemaVersion, recipe: result.recipe }, null, 2);
}

async function onClick(id, action) {
  $(id).addEventListener("click", async () => {
    $(id).disabled = true;
    try { await action(); } catch (error) { show(error.message, true); }
    finally { $(id).disabled = false; }
  });
}

async function main() {
  config = await checkedJson(await fetch("./config.json", { cache: "no-store" }));
  if (`${location.origin}${location.pathname}` !== config.redirectUri) {
    throw new Error(`Open the exact registered address: ${config.redirectUri}`);
  }
  $("environment").textContent = `Isolated AWS POC · us-east-2 · ${config.apiBaseUrl}`;
  $("recipe-json").value = JSON.stringify(await checkedJson(await fetch("./sample-recipe.json")), null, 2);

  const params = new URLSearchParams(location.search);
  try {
  if (params.has("code") || params.has("error")) {
    const saved = sessionStorage.getItem(TRANSACTION_KEY);
    sessionStorage.removeItem(TRANSACTION_KEY); // Consume the transaction even on failure.
    history.replaceState({}, "", config.redirectUri); // Remove the code before any token request.
    const { code, verifier } = validateCallback(params, saved ? JSON.parse(saved) : null, config.redirectUri);
    const tokens = await checkedJson(await fetch(new URL("/oauth2/token", config.authDomain), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ grant_type: "authorization_code", client_id: config.clientId,
        code, redirect_uri: config.redirectUri, code_verifier: verifier }),
      referrerPolicy: "no-referrer",
    }));
    if (typeof tokens.access_token !== "string" || tokens.token_type?.toLowerCase() !== "bearer" || !Number.isFinite(tokens.expires_in)) {
      throw new Error("Cognito returned an invalid token response.");
    }
    accessToken = tokens.access_token;
    expiresAt = Date.now() + tokens.expires_in * 1000;
    // ID and refresh tokens are deliberately discarded. Nothing is placed in localStorage.
    $("session").textContent = "Signed in. The API verifies your access token on each request.";
    show("Sign-in complete. Save a sample recipe, then load it.");
  }

  } catch (error) {
    accessToken = null;
    expiresAt = 0;
    show(`Sign-in could not complete: ${error.message}`, true);
  }

  await onClick("sign-in", async () => {
    const { url, transaction } = await beginLogin(config);
    sessionStorage.setItem(TRANSACTION_KEY, JSON.stringify(transaction));
    location.assign(url);
  });
  await onClick("sign-out", async () => {
    accessToken = null;
    expiresAt = 0;
    sessionStorage.removeItem(TRANSACTION_KEY);
    const url = new URL("/logout", config.authDomain);
    url.search = new URLSearchParams({ client_id: config.clientId, logout_uri: config.redirectUri });
    location.assign(url);
  });
  await onClick("save", async () => {
    const body = JSON.parse($("recipe-json").value);
    if (body.recipe?.id !== $("recipe-id").value.trim()) throw new Error("The recipe document ID must match the Recipe ID field.");
    body.recipe.updatedAt = new Date().toISOString();
    await api("PUT", body);
  });
  await onClick("load", () => api("GET"));
  await onClick("unauthenticated", async () => {
    const result = await fetch(`${config.apiBaseUrl}/recipes/${encodeURIComponent($("recipe-id").value.trim())}`, { cache: "no-store" });
    if (result.status !== 401) throw new Error(`Expected 401 without a token; received ${result.status}.`);
    show("Passed: API returned 401 for a request without a token.");
  });
  for (const button of document.querySelectorAll("button")) button.disabled = false;
}

main().catch((error) => show(`Setup/sign-in failed: ${error.message}. Generate config.json from Terraform outputs and use the registered callback URL.`, true));
