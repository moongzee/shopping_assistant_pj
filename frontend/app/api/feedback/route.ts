export const runtime = "nodejs";

const debugEnabled = String(process.env.API_DEBUG || "").trim() === "true";

function debugLog(message: string, payload?: Record<string, any>) {
  if (!debugEnabled) return;
  if (payload) console.log(message, payload);
  else console.log(message);
}

function backendBaseUrl() {
  return process.env.AGENT_BASE_URL || "http://127.0.0.1:8000";
}

export async function POST(req: Request) {
  const startedAt = Date.now();
  const body = await req.text();
  const bodyPreview = body.length > 2000 ? `${body.slice(0, 2000)}...<truncated>` : body;
  debugLog("[api/feedback] request", {
    url: req.url,
    bodyLength: body.length,
    bodyPreview,
  });
  const upstream = await fetch(`${backendBaseUrl()}/v1/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const text = await upstream.text();
  const textPreview = text.length > 2000 ? `${text.slice(0, 2000)}...<truncated>` : text;
  debugLog("[api/feedback] upstream", {
    status: upstream.status,
    contentType: upstream.headers.get("content-type"),
    durationMs: Date.now() - startedAt,
    responsePreview: textPreview,
  });
  return new Response(text, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}

