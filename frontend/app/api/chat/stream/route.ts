export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

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
  debugLog("[api/chat/stream] request", {
    url: req.url,
    bodyLength: body.length,
    bodyPreview,
  });
  const upstream = await fetch(`${backendBaseUrl()}/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    cache: "no-store",
  });
  debugLog("[api/chat/stream] upstream", {
    status: upstream.status,
    contentType: upstream.headers.get("content-type"),
    durationMs: Date.now() - startedAt,
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") || "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}

