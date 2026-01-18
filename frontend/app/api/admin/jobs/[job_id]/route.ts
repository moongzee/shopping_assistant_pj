import { proxyJsonGET } from "../../_util";

export async function GET(_req: Request, ctx: { params: Promise<{ job_id: string }> }) {
  const { job_id: jobId } = await ctx.params;
  return proxyJsonGET(`/admin/jobs/${encodeURIComponent(jobId)}`);
}

