import { proxyJsonGET } from "../../_util";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const limit = url.searchParams.get("limit") || "200";
  return proxyJsonGET(`/admin/logs/feedback?limit=${encodeURIComponent(limit)}`);
}

