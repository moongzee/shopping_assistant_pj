import { proxyJsonPOST } from "../_util";

export async function POST(req: Request) {
  const bodyText = await req.text();
  return proxyJsonPOST("/admin/reload_artifacts", bodyText || "{}");
}

