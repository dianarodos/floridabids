// Florida Bids — Cloudflare Worker: serves the static site (site/) and the small email-list API.
//
//   POST /api/subscribe     {email, freq: daily|weekly}  -> stores as pending, sends a confirmation email
//   GET  /api/confirm?t=…   -> activates the subscription, redirects to /?confirmed=1
//   GET  /api/unsubscribe?t=…  (link in every email) and POST (one-click unsubscribe from mail apps)
//   GET  /api/stats         -> {subscribers, daily, weekly}  (shown on the page)
//   GET  /api/admin/subscribers?freq=daily|weekly   (Bearer ADMIN_TOKEN; used by the daily GitHub job)
//   GET  /api/admin/export.csv                       (Bearer ADMIN_TOKEN; full list for Diana)
//   POST /api/admin/run-daily                        (Bearer ADMIN_TOKEN; same as the cron, for testing)
//
// Cron (wrangler.jsonc "triggers"): starts the daily GitHub run, because GitHub's own schedule runs hours
// late or not at all. A second, later cron is the backup: each one starts the run only if no full run
// has already started or succeeded today. Needs the GH_TOKEN secret (fine-grained token, Actions: write).
//
// Bindings (wrangler.jsonc): ASSETS (site/), DB (D1). Secrets: BREVO_API_KEY, ADMIN_TOKEN, GH_TOKEN.
// Vars: SITE_URL, FROM_EMAIL, FROM_NAME.

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS subscribers (
     email TEXT PRIMARY KEY,
     freq TEXT NOT NULL DEFAULT 'daily',
     status TEXT NOT NULL DEFAULT 'pending',      -- pending | active | unsubscribed
     token TEXT NOT NULL,
     created_at TEXT NOT NULL,
     confirmed_at TEXT,
     unsubscribed_at TEXT,
     ip_hash TEXT,
     confirm_sent_at TEXT
   )`,
  `CREATE INDEX IF NOT EXISTS subscribers_token ON subscribers(token)`,
  `CREATE INDEX IF NOT EXISTS subscribers_ip ON subscribers(ip_hash, created_at)`,
];
let schemaReady = false;

const EMAIL_RE = /^[^@\s<>"']{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}$/;

const REPO = "dianarodos/floridabids";
const RUN_NAME = "Daily bid update";          // run-name of full runs in .github/workflows/daily.yml

export default {
  async scheduled(event, env, ctx) {
    const test = event.cron === "55 13 * * *" ? "baker-county" : "";   // TEMP: one-time check that GH_TOKEN works
    ctx.waitUntil(startDailyRun(env, event.cron, test).catch(e => console.error("daily run trigger failed:", e)));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    try {
      await ensureSchema(env);
      const route = `${request.method} ${url.pathname}`;
      switch (route) {
        case "POST /api/subscribe": return await subscribe(request, env);
        case "GET /api/confirm": return await confirm(url, env);
        case "GET /api/unsubscribe": return await unsubscribe(url, env, false);
        case "POST /api/unsubscribe": return await unsubscribe(url, env, true);
        case "GET /api/stats": return await stats(env);
        case "GET /api/admin/subscribers": return await adminList(request, url, env);
        case "GET /api/admin/export.csv": return await adminCsv(request, env);
        case "POST /api/admin/run-daily": {                            // test the cron path by hand
          if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
          await startDailyRun(env, "manual", url.searchParams.get("only") || "");
          return json({ ok: true });
        }
      }
      return json({ error: "not found" }, 404);
    } catch (e) {
      console.error(e);
      return json({ error: "server error" }, 500);
    }
  },
};

async function startDailyRun(env, cron, only = "") {
  if (!env.GH_TOKEN) { console.error("GH_TOKEN secret not set; cannot start the daily run"); return; }
  const gh = (path, init = {}) => fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "floridabids-cron", ...(init.headers || {}) },
  });
  const today = new Date().toISOString().slice(0, 10);       // crons fire after 10:00 UTC, i.e. same day in Florida
  const r = await gh(`/actions/workflows/daily.yml/runs?per_page=30&created=>=${today}`);
  if (!r.ok) throw new Error(`list runs ${r.status}: ${await r.text()}`);
  const { workflow_runs = [] } = await r.json();
  const done = !only && workflow_runs.find(w => w.display_title === RUN_NAME && (w.status !== "completed" || w.conclusion === "success"));
  if (done) { console.log(`cron ${cron}: today's run already ${done.status} (${done.html_url}); nothing to do`); return; }
  const d = await gh("/actions/workflows/daily.yml/dispatches", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main", inputs: { only, send_email: only ? "no" : "yes" } }),   // "only" = small test run, no email
  });
  if (!d.ok) throw new Error(`dispatch ${d.status}: ${await d.text()}`);
  console.log(`cron ${cron}: started ${only ? "a test run of " + only : "today's daily run"}`);
}

async function ensureSchema(env) {
  if (schemaReady) return;
  for (const sql of SCHEMA) await env.DB.prepare(sql).run();
  schemaReady = true;
}

async function subscribe(request, env) {
  let body;
  try { body = await request.json(); } catch { return json({ error: "bad request" }, 400); }
  if (body.website) return json({ ok: true });                       // honeypot field: bots fill it, people don't
  const email = String(body.email || "").trim().toLowerCase();
  const freq = body.freq === "weekly" ? "weekly" : "daily";
  if (!EMAIL_RE.test(email)) return json({ error: "invalid email" }, 400);

  const ipHash = await sha256((request.headers.get("cf-connecting-ip") || "") + (env.ADMIN_TOKEN || ""));
  const hourAgo = new Date(Date.now() - 3600e3).toISOString();
  const recent = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM subscribers WHERE ip_hash = ? AND created_at > ?").bind(ipHash, hourAgo).first();
  if ((recent?.n || 0) >= 5) return json({ error: "too many sign-ups, try again later" }, 429);

  const now = new Date().toISOString();
  const existing = await env.DB.prepare("SELECT * FROM subscribers WHERE email = ?").bind(email).first();
  if (existing && existing.status === "active") {
    if (existing.freq !== freq) await env.DB.prepare("UPDATE subscribers SET freq = ? WHERE email = ?").bind(freq, email).run();
    return json({ ok: true, already: true });                       // don't reveal more than that
  }
  if (existing && existing.confirm_sent_at && Date.now() - Date.parse(existing.confirm_sent_at) < 10 * 60e3) {
    return json({ ok: true });                                      // a confirmation went out minutes ago
  }
  const token = existing?.token || randomToken();
  if (existing) {
    await env.DB.prepare("UPDATE subscribers SET freq = ?, status = 'pending', confirm_sent_at = ? WHERE email = ?")
      .bind(freq, now, email).run();
  } else {
    await env.DB.prepare(
      "INSERT INTO subscribers (email, freq, status, token, created_at, ip_hash, confirm_sent_at) VALUES (?, ?, 'pending', ?, ?, ?, ?)")
      .bind(email, freq, token, now, ipHash, now).run();
  }
  await sendConfirmation(env, email, freq, token);
  return json({ ok: true });
}

async function confirm(url, env) {
  const t = url.searchParams.get("t") || "";
  const row = t && await env.DB.prepare("SELECT email, status FROM subscribers WHERE token = ?").bind(t).first();
  if (!row) return Response.redirect(`${env.SITE_URL}/?confirmed=0`, 302);
  if (row.status !== "active") {
    await env.DB.prepare("UPDATE subscribers SET status = 'active', confirmed_at = ? WHERE token = ?")
      .bind(new Date().toISOString(), t).run();
  }
  return Response.redirect(`${env.SITE_URL}/?confirmed=1`, 302);
}

async function unsubscribe(url, env, oneClick) {
  const t = url.searchParams.get("t") || "";
  const row = t && await env.DB.prepare("SELECT email FROM subscribers WHERE token = ?").bind(t).first();
  if (row) {
    await env.DB.prepare("UPDATE subscribers SET status = 'unsubscribed', unsubscribed_at = ? WHERE token = ?")
      .bind(new Date().toISOString(), t).run();
  }
  if (oneClick) return new Response("Unsubscribed", { status: 200 });
  return Response.redirect(`${env.SITE_URL}/?unsubscribed=${row ? 1 : 0}`, 302);
}

async function stats(env) {
  const r = await env.DB.prepare(
    "SELECT SUM(freq = 'daily') AS daily, SUM(freq = 'weekly') AS weekly, COUNT(*) AS n FROM subscribers WHERE status = 'active'").first();
  return json({ subscribers: r?.n || 0, daily: r?.daily || 0, weekly: r?.weekly || 0 },
    200, { "Cache-Control": "public, max-age=300" });
}

function authorized(request, env) {
  if (!env.ADMIN_TOKEN) return false;
  const h = request.headers.get("authorization") || "";
  // ?key= lets Diana open the CSV export straight from a browser bookmark
  const key = new URL(request.url).searchParams.get("key") || "";
  return h === `Bearer ${env.ADMIN_TOKEN}` || key === env.ADMIN_TOKEN;
}

async function adminList(request, url, env) {
  if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
  const freq = url.searchParams.get("freq");
  const q = freq
    ? env.DB.prepare("SELECT email, freq, token FROM subscribers WHERE status = 'active' AND freq = ?").bind(freq)
    : env.DB.prepare("SELECT email, freq, token FROM subscribers WHERE status = 'active'");
  const { results } = await q.all();
  return json({ subscribers: results });
}

async function adminCsv(request, env) {
  if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
  const { results } = await env.DB.prepare(
    "SELECT email, freq, status, created_at, confirmed_at, unsubscribed_at FROM subscribers ORDER BY created_at").all();
  const cols = ["email", "freq", "status", "created_at", "confirmed_at", "unsubscribed_at"];
  const csv = [cols.join(",")].concat(results.map(r => cols.map(c => `"${String(r[c] ?? "").replace(/"/g, '""')}"`).join(","))).join("\n");
  return new Response(csv, { headers: { "Content-Type": "text/csv; charset=utf-8", "Cache-Control": "no-store",
    "Content-Disposition": 'attachment; filename="floridabids-subscribers.csv"' } });
}

async function sendConfirmation(env, email, freq, token) {
  const link = `${env.SITE_URL}/api/confirm?t=${token}`;
  const html = `<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.5;color:#1b2b28;max-width:520px">
  <h2 style="font-family:Georgia,serif;margin:0 0 12px">Confirm your Florida Bids email</h2>
  <p>Someone (hopefully you) asked to get the list of open Florida government bids <b>${freq === "weekly" ? "every Monday" : "every morning"}</b> at this address.</p>
  <p><a href="${link}" style="display:inline-block;background:#0d5c50;color:#fff;padding:11px 18px;border-radius:6px;text-decoration:none;font-weight:bold">Yes, send me the list</a></p>
  <p style="color:#5b6b67;font-size:13px">If you didn't ask for this, ignore this email and you won't hear from us again. We never send ads.</p>
  <p style="color:#5b6b67;font-size:13px">Florida Bids &middot; <a href="${env.SITE_URL}" style="color:#0d5c50">${env.SITE_URL.replace(/^https?:\/\//, "")}</a></p></div>`;
  const r = await fetch("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: { "api-key": env.BREVO_API_KEY, "Content-Type": "application/json", accept: "application/json" },
    body: JSON.stringify({
      sender: { email: env.FROM_EMAIL, name: env.FROM_NAME || "Florida Bids" },
      to: [{ email }],
      subject: "Confirm your Florida Bids email",
      htmlContent: html,
      textContent: `Confirm your Florida Bids email: ${link}\n\nIf you didn't ask for this, ignore this email.`,
      tags: ["confirm"],
    }),
  });
  if (!r.ok) throw new Error(`Brevo ${r.status}: ${await r.text()}`);
}

function json(obj, status = 200, headers = {}) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", ...headers } });
}

function randomToken() {
  const b = new Uint8Array(24);
  crypto.getRandomValues(b);
  return btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sha256(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map(x => x.toString(16).padStart(2, "0")).join("").slice(0, 32);
}
