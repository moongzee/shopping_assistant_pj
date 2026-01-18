"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

type Job = { job_id: string; status: string; result?: any; error?: string };

async function jget(url: string) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}`);
  return await r.json();
}

async function jpost(url: string, body: any) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status}`);
  return await r.json();
}

export default function AdminPage() {
  const [chatRows, setChatRows] = useState<any[]>([]);
  const [fbRows, setFbRows] = useState<any[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const logsTail = (job as any)?.logs_tail as any[] | undefined;
  const progress = (job as any)?.progress as any | undefined;
  const [compileModule, setCompileModule] = useState<string>("product_ranker");
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());
  const [qualityLabels, setQualityLabels] = useState<Record<string, "good" | "bad" | "unknown">>({});
  const [curationMsg, setCurationMsg] = useState<string | null>(null);

  const defaults = useMemo(() => {
    if (compileModule === "relaxed_constraints")
      return {
        dataset: "agent/data/datasets/relaxed_constraints.jsonl",
        out: "agent/artifacts/relaxed_constraints.json",
      };
    if (compileModule === "fusion_decision")
      return {
        dataset: "agent/data/datasets/fusion.jsonl",
        out: "agent/artifacts/fusion_decision.json",
      };
    return {
      dataset: "agent/data/datasets/ranker.jsonl",
      out: "agent/artifacts/product_ranker.json",
    };
  }, [compileModule]);

  const [datasetPath, setDatasetPath] = useState<string>(defaults.dataset);
  const [outPath, setOutPath] = useState<string>(defaults.out);

  useEffect(() => {
    setDatasetPath(defaults.dataset);
    setOutPath(defaults.out);
  }, [defaults.dataset, defaults.out]);

  async function refreshLogs() {
    setBusy("logs");
    try {
      const c = await jget("/api/admin/logs/chat?limit=200");
      const f = await jget("/api/admin/logs/feedback?limit=200");
      setChatRows(c.rows ?? []);
      setFbRows(f.rows ?? []);
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    refreshLogs().catch(() => {});
  }, []);

  async function refreshCuration() {
    try {
      const r = await jget("/api/admin/curation/state");
      const ex = Array.isArray(r.excluded_message_ids) ? r.excluded_message_ids : [];
      const q = r.quality_labels && typeof r.quality_labels === "object" ? r.quality_labels : {};
      setExcludedIds(new Set(ex.filter((x: any) => typeof x === "string" && x)));
      const mapped: Record<string, "good" | "bad" | "unknown"> = {};
      for (const [k, v] of Object.entries(q)) {
        if (v === "good" || v === "bad" || v === "unknown") mapped[k] = v;
      }
      setQualityLabels(mapped);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    refreshCuration().catch(() => {});
  }, []);

  function toggleExclude(mid: string) {
    setCurationMsg(null);
    setExcludedIds((prev) => {
      const next = new Set(prev);
      if (next.has(mid)) next.delete(mid);
      else next.add(mid);
      return next;
    });
  }

  function setQuality(mid: string, v: "good" | "bad" | "unknown") {
    setCurationMsg(null);
    setQualityLabels((prev) => ({ ...prev, [mid]: v }));
  }

  async function saveCuration() {
    setBusy("curation");
    setCurationMsg(null);
    try {
      const payload = {
        excluded_message_ids: Array.from(excludedIds),
        quality_labels: qualityLabels,
      };
      await jpost("/api/admin/curation/state", payload);
      setCurationMsg("정제 규칙 저장 완료");
      await refreshCuration();
    } catch (e: any) {
      setCurationMsg(`저장 실패: ${String(e?.message ?? e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function reloadArtifacts() {
    setBusy("reload");
    try {
      await jpost("/api/admin/reload_artifacts", {});
      await refreshLogs();
    } finally {
      setBusy(null);
    }
  }

  async function buildDatasets() {
    setBusy("datasets");
    try {
      const r = await jpost("/api/admin/datasets/build", { async_run: true });
      if (r.job_id) setJob({ job_id: r.job_id, status: "queued" });
    } finally {
      setBusy(null);
    }
  }

  async function compile() {
    setBusy("compile");
    try {
      const r = await jpost("/api/admin/compile", {
        module: compileModule,
        dataset: datasetPath,
        out: outPath,
        reload_artifacts: true,
        async_run: true,
      });
      if (r.job_id) setJob({ job_id: r.job_id, status: "queued" });
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    if (!job?.job_id) return;
    let alive = true;
    const tick = async () => {
      try {
        const r = await jget(`/api/admin/jobs/${job.job_id}`);
        if (!alive) return;
        setJob(r);
        if (r.status === "done" || r.status === "error") {
          refreshLogs().catch(() => {});
          return;
        }
      } catch {
        // ignore
      }
      if (alive) setTimeout(tick, 1500);
    };
    tick();
    return () => {
      alive = false;
    };
  }, [job?.job_id]);

  return (
    <>
      <div className="header">
        <div className="brand">
          <h1>학습/최적화 대시보드</h1>
          <span className="pill">로그 → dataset → compile → reload</span>
        </div>
        <Link className="pill" href="/">
          ← 채팅으로
        </Link>
      </div>

      <div className="grid">
        <div className="panel">
          <div className="panelHeader">
            <div className="panelTitle">Actions</div>
            <div className="pill">{busy ? `busy: ${busy}` : "idle"}</div>
          </div>
          <div className="panelBody">
            <div className="row" style={{ marginBottom: 10 }}>
              <button className="button" onClick={refreshLogs} disabled={!!busy}>
                로그 새로고침
              </button>
              <button className="button" onClick={saveCuration} disabled={!!busy}>
                정제 규칙 저장
              </button>
              <button className="button" onClick={buildDatasets} disabled={!!busy}>
                dataset 생성
              </button>
              <button className="button" onClick={reloadArtifacts} disabled={!!busy}>
                artifacts reload
              </button>
            </div>
            {curationMsg ? (
              <div className="small" style={{ marginBottom: 10 }}>
                {curationMsg}
              </div>
            ) : null}

            <div className="msg" style={{ marginBottom: 10 }}>
              <div className="msgRole">Compile</div>
              <div className="row" style={{ marginBottom: 10 }}>
                <select
                  className="input"
                  value={compileModule}
                  onChange={(e) => setCompileModule(e.target.value)}
                  style={{ width: "40%" }}
                >
                  <option value="product_ranker">product_ranker</option>
                  <option value="fusion_decision">fusion_decision</option>
                  <option value="relaxed_constraints">relaxed_constraints</option>
                </select>
                <button className="button" onClick={compile} disabled={!!busy}>
                  compile 실행
                </button>
              </div>
              <div className="row" style={{ marginBottom: 10 }}>
                <input
                  className="input"
                  value={datasetPath}
                  onChange={(e) => setDatasetPath(e.target.value)}
                  placeholder="dataset path"
                />
              </div>
              <div className="row">
                <input
                  className="input"
                  value={outPath}
                  onChange={(e) => setOutPath(e.target.value)}
                  placeholder="artifact out path"
                />
              </div>
            </div>

            <div className="msg">
              <div className="msgRole">Job</div>
              <div
                className="msgText"
                style={{
                  maxHeight: 220,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  paddingRight: 6,
                }}
              >
                {job ? JSON.stringify(job, null, 2) : "대기중"}
              </div>
            </div>

            <div className="msg" style={{ marginTop: 10 }}>
              <div className="msgRole">학습 진행 로그 (tail)</div>
              <div className="small" style={{ marginBottom: 6 }}>
                {progress?.step ? `STEP ${progress.step}` : ""}{" "}
                {progress?.trial ? `Trial ${progress.trial}/${progress.trial_total ?? "?"}` : ""}
              </div>
              <div
                className="msgText"
                style={{
                  maxHeight: 260,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  paddingRight: 6,
                }}
              >
                {logsTail && logsTail.length ? logsTail.join("\n") : "로그 대기중"}
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panelHeader">
            <div className="panelTitle">최근 로그 (chat / feedback)</div>
            <div className="pill">
              chat: {chatRows.length} / feedback: {fbRows.length}
            </div>
          </div>
          <div className="panelBody">
            <div className="msg" style={{ marginBottom: 10 }}>
              <div className="msgRole">정제(품질/제외) - 최근 chat 기준</div>
              <div className="small" style={{ marginBottom: 8 }}>
                - 제외(exclude): dataset 생성/compile 대상에서 제외됨<br />
                - 품질 라벨 bad: 기본적으로 dataset 생성에서 제외됨
              </div>
              <div
                className="msgText"
                style={{
                  maxHeight: 260,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  paddingRight: 6,
                }}
              >
                {(chatRows.slice(-50) || []).reverse().map((row: any, idx: number) => {
                  const mid = String(row?.message_id ?? "");
                  if (!mid) return null;
                  const q = String(row?.user_query ?? "");
                  const err = row?.error ? String(row.error) : "";
                  const recCount = row?.recommended_products_count ?? "";
                  const isExcluded = excludedIds.has(mid);
                  const quality = qualityLabels[mid] ?? "unknown";
                  return (
                    <div key={mid + idx} style={{ marginBottom: 10, paddingBottom: 10, borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                      <div className="small">
                        <b>message_id</b>: {mid}{" "}
                        <span style={{ marginLeft: 8 }}>
                          <b>추천수</b>: {String(recCount)}
                        </span>
                        {err ? (
                          <span style={{ marginLeft: 8, color: "rgba(251, 113, 133, 0.95)" }}>
                            <b>error</b>: {err.slice(0, 120)}
                          </span>
                        ) : null}
                      </div>
                      <div className="small" style={{ marginTop: 4 }}>
                        <b>query</b>: {q}
                      </div>
                      <div className="row" style={{ marginTop: 8 }}>
                        <button
                          className="button"
                          style={{
                            padding: "8px 10px",
                            borderColor: isExcluded ? "rgba(251, 113, 133, 0.7)" : undefined,
                            background: isExcluded ? "rgba(251, 113, 133, 0.18)" : undefined,
                          }}
                          onClick={() => toggleExclude(mid)}
                          disabled={!!busy}
                        >
                          {isExcluded ? "제외 해제" : "제외"}
                        </button>
                        <button
                          className="button"
                          style={{
                            padding: "8px 10px",
                            borderColor: quality === "good" ? "rgba(52, 211, 153, 0.65)" : undefined,
                            background: quality === "good" ? "rgba(52, 211, 153, 0.18)" : undefined,
                          }}
                          onClick={() => setQuality(mid, "good")}
                          disabled={!!busy}
                        >
                          good
                        </button>
                        <button
                          className="button"
                          style={{
                            padding: "8px 10px",
                            borderColor: quality === "bad" ? "rgba(251, 113, 133, 0.7)" : undefined,
                            background: quality === "bad" ? "rgba(251, 113, 133, 0.18)" : undefined,
                          }}
                          onClick={() => setQuality(mid, "bad")}
                          disabled={!!busy}
                        >
                          bad
                        </button>
                        <button
                          className="button"
                          style={{
                            padding: "8px 10px",
                            borderColor: quality === "unknown" ? "rgba(255,255,255,0.2)" : undefined,
                            background: quality === "unknown" ? "rgba(255,255,255,0.06)" : undefined,
                          }}
                          onClick={() => setQuality(mid, "unknown")}
                          disabled={!!busy}
                        >
                          unknown
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="msg" style={{ marginBottom: 10 }}>
              <div className="msgRole">chat.jsonl (tail)</div>
              <div
                className="msgText"
                style={{
                  maxHeight: 220,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  paddingRight: 6,
                }}
              >
                {JSON.stringify(chatRows.slice(-50), null, 2)}
              </div>
            </div>
            <div className="msg">
              <div className="msgRole">feedback.jsonl (tail)</div>
              <div
                className="msgText"
                style={{
                  maxHeight: 220,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  paddingRight: 6,
                }}
              >
                {JSON.stringify(fbRows.slice(-50), null, 2)}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

