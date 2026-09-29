const API_ROOT = "https://api.github.com";
const SESSION_TTL_SECONDS = 3600;
const STATE_TTL_SECONDS = 600;

function randomToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
}

function json(body, status = 200, origin = "") {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Authorization, Content-Type",
      "Vary": "Origin",
      "Cache-Control": "no-store",
    },
  });
}

function requireOrigin(request, env) {
  return request.headers.get("Origin") === env.PUBLIC_ORIGIN;
}

function requirePageNavigation(request, env) {
  if (requireOrigin(request, env)) return true;
  try {
    return new URL(request.headers.get("Referer") || "").origin === env.PUBLIC_ORIGIN;
  } catch {
    return false;
  }
}

async function github(token, path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "tennis-liquidity-dashboard",
      ...options.headers,
    },
  });
  return response;
}

function callbackPage(session, env) {
  const origin = JSON.stringify(env.PUBLIC_ORIGIN);
  const token = JSON.stringify(session);
  return new Response(`<!doctype html><meta charset="utf-8"><title>Refresh authorized</title>
<p>Signed in. You can close this window and return to the dashboard.</p>
<script>if(window.opener){window.opener.postMessage({type:"refresh-session",token:${token}},${origin});window.close()}</script>`, {
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}

async function startAuth(request, env) {
  if (!requirePageNavigation(request, env)) return new Response("Forbidden", { status: 403 });
  const state = randomToken();
  await env.SESSIONS.put(`state:${state}`, "pending", { expirationTtl: STATE_TTL_SECONDS });
  const callback = `${new URL(request.url).origin}/auth/callback`;
  const authorize = new URL("https://github.com/login/oauth/authorize");
  authorize.searchParams.set("client_id", env.GITHUB_APP_CLIENT_ID);
  authorize.searchParams.set("redirect_uri", callback);
  authorize.searchParams.set("state", state);
  return Response.redirect(authorize.toString(), 302);
}

async function finishAuth(request, env) {
  const url = new URL(request.url);
  const state = url.searchParams.get("state") || "";
  const code = url.searchParams.get("code") || "";
  const stateKey = `state:${state}`;
  if (!state || !code || !(await env.SESSIONS.get(stateKey))) {
    return new Response("Invalid or expired sign-in request.", { status: 400 });
  }
  await env.SESSIONS.delete(stateKey);
  const tokenResponse = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { "Accept": "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: env.GITHUB_APP_CLIENT_ID,
      client_secret: env.GITHUB_APP_CLIENT_SECRET,
      code,
      redirect_uri: `${url.origin}/auth/callback`,
      state,
    }),
  });
  if (!tokenResponse.ok) return new Response("GitHub sign-in failed.", { status: 502 });
  const tokenData = await tokenResponse.json();
  if (!tokenData.access_token) return new Response("GitHub sign-in was not authorized.", { status: 401 });

  const session = randomToken();
  await env.SESSIONS.put(`session:${session}`, tokenData.access_token, {
    expirationTtl: SESSION_TTL_SECONDS,
  });
  return callbackPage(session, env);
}

async function sessionToken(request, env) {
  const authorization = request.headers.get("Authorization") || "";
  const match = authorization.match(/^Bearer ([A-Za-z0-9_-]+)$/);
  return match ? env.SESSIONS.get(`session:${match[1]}`) : null;
}

async function dispatchRefresh(request, env) {
  if (!requireOrigin(request, env)) return json({ error: "Forbidden origin." }, 403, env.PUBLIC_ORIGIN);
  const token = await sessionToken(request, env);
  if (!token) return json({ error: "Sign in again to refresh the dashboard." }, 401, env.PUBLIC_ORIGIN);
  const requestId = randomToken();
  const requestedAt = new Date().toISOString();
  const response = await github(
    token,
    `/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.WORKFLOW_ID}/dispatches`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ref: "main",
        inputs: { refresh_request_id: requestId },
      }),
    },
  );
  if (!response.ok) {
    return json({
      error: response.status === 403 || response.status === 404
        ? "Your GitHub account needs write access to this repository to start a refresh."
        : `GitHub could not start the refresh (HTTP ${response.status}).`,
    }, response.status === 403 || response.status === 404 ? 403 : 502, env.PUBLIC_ORIGIN);
  }
  await env.SESSIONS.put(`request:${requestedAt}`, requestId, {
    expirationTtl: SESSION_TTL_SECONDS,
  });
  return json({ accepted: true, requested_at: requestedAt }, 202, env.PUBLIC_ORIGIN);
}

async function refreshStatus(request, env) {
  if (!requireOrigin(request, env)) return json({ error: "Forbidden origin." }, 403, env.PUBLIC_ORIGIN);
  const token = await sessionToken(request, env);
  if (!token) return json({ error: "Sign in again to check refresh status." }, 401, env.PUBLIC_ORIGIN);
  const requestedAt = new URL(request.url).searchParams.get("since") || "";
  const requestId = await env.SESSIONS.get(`request:${requestedAt}`);
  if (!requestId) return json({ error: "Refresh request expired. Start a new refresh." }, 404, env.PUBLIC_ORIGIN);
  const runsResponse = await github(
    token,
    `/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.WORKFLOW_ID}/runs?event=workflow_dispatch&per_page=10`,
  );
  if (!runsResponse.ok) return json({ error: "Unable to check the GitHub refresh status." }, 502, env.PUBLIC_ORIGIN);
  const payload = await runsResponse.json();
  const run = (payload.workflow_runs || []).find(
    item => item.display_title?.includes(requestId),
  );
  if (!run) return json({ status: "queued" }, 200, env.PUBLIC_ORIGIN);
  return json({
    status: run.status,
    conclusion: run.conclusion,
    run_url: run.html_url,
    created_at: run.created_at,
  }, 200, env.PUBLIC_ORIGIN);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return requireOrigin(request, env)
        ? new Response(null, {
          headers: {
            "Access-Control-Allow-Origin": env.PUBLIC_ORIGIN,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Vary": "Origin",
          },
        })
        : new Response("Forbidden", { status: 403 });
    }
    if (url.pathname === "/auth/start" && request.method === "GET") return startAuth(request, env);
    if (url.pathname === "/auth/callback" && request.method === "GET") return finishAuth(request, env);
    if (url.pathname === "/api/refresh" && request.method === "POST") return dispatchRefresh(request, env);
    if (url.pathname === "/api/refresh/status" && request.method === "GET") return refreshStatus(request, env);
    return new Response("Not found", { status: 404 });
  },
};
