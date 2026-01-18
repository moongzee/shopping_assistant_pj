export const runtime = "nodejs";

function backendBaseUrl() {
  return process.env.AGENT_BASE_URL || "http://127.0.0.1:8000";
}

export async function POST(req: Request) {
  const body = await req.text();
  const upstream = await fetch(`${backendBaseUrl()}/v1/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}

