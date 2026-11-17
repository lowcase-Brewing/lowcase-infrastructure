const base64url = (bytes) => btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");

export async function pkceChallenge(verifier) {
  return base64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
}

export async function beginLogin(config, now = Date.now()) {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const state = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const url = new URL("/oauth2/authorize", config.authDomain);
  url.search = new URLSearchParams({
    client_id: config.clientId,
    response_type: "code",
    redirect_uri: config.redirectUri,
    scope: config.scopes.join(" "),
    state,
    code_challenge_method: "S256",
    code_challenge: await pkceChallenge(verifier),
  });
  return { url, transaction: { state, verifier, redirectUri: config.redirectUri, createdAt: now } };
}

export function validateCallback(params, transaction, redirectUri, now = Date.now()) {
  if (!transaction || typeof transaction.state !== "string" ||
      !/^[A-Za-z0-9_-]{43}$/.test(transaction.state) || params.get("state") !== transaction.state ||
      transaction.redirectUri !== redirectUri || typeof transaction.verifier !== "string" ||
      !/^[A-Za-z0-9_-]{43}$/.test(transaction.verifier) ||
      !Number.isFinite(transaction.createdAt) ||
      now < transaction.createdAt || now - transaction.createdAt > 10 * 60 * 1000) {
    throw new Error("Login state is missing, expired, or mismatched. Start sign-in again.");
  }
  if (params.has("error")) throw new Error(`Cognito sign-in failed: ${params.get("error")}`);
  const code = params.get("code");
  if (!code) throw new Error("Cognito did not return an authorization code.");
  return { code, verifier: transaction.verifier };
}
