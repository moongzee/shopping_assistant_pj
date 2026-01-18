export const runtime = "nodejs";

export function backendBaseUrl() {
  return process.env.AGENT_BASE_URL || "http://127.0.0.1:8000";
}

export function adminKey() {
  return process.env.ADMIN_API_KEY || "";
}

export async function proxyJsonGET(path: string) {
  const r = await fetch(`${backendBaseUrl()}${path}`, {
    headers: adminKey() ? { "x-admin-key": adminKey() } : {},
  });
  const text = await r.text();
  return new Response(text, { status: r.status, headers: { "content-type": "application/json" } });
}

export async function proxyJsonPOST(path: string, bodyText: string) {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (adminKey()) headers["x-admin-key"] = adminKey();
  const r = await fetch(`${backendBaseUrl()}${path}`, { method: "POST", headers, body: bodyText });
  const text = await r.text();
  return new Response(text, { status: r.status, headers: { "content-type": "application/json" } });
}

