export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

function backendBaseUrl() {
  return process.env.AGENT_BASE_URL || "http://127.0.0.1:8000";
}

export async function POST(req: Request) {
  const body = await req.text();
  const upstream = await fetch(`${backendBaseUrl()}/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    cache: "no-store",
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

