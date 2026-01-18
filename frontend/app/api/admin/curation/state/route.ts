import { proxyJsonGET, proxyJsonPOST } from "../../_util";

export async function GET(_req: Request) {
  return proxyJsonGET("/admin/curation/state");
}

export async function POST(req: Request) {
  const bodyText = await req.text();
  return proxyJsonPOST("/admin/curation/state", bodyText || "{}");
}

