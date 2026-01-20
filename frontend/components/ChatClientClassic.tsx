"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { parseSseStream } from "@/lib/sse";

type ChatStep = { category: string; label: string };
type ChatMsg = {
  role: "user" | "assistant";
  text: string;
  steps?: ChatStep[];
  done?: boolean;
  currentStage?: string | null;
};

type Product = Record<string, any>;

function pick(v: any, ...keys: string[]) {
  for (const k of keys) {
    const val = v?.[k];
    if (val !== undefined && val !== null && String(val).trim() !== "") return val;
  }
  return undefined;
}

const STAGE_ORDER = [
  "요청 접수",
  "추천 생성",
  "상품데이터검색",
  "리뷰데이터검색",
  "추천종합",
  "응답",
];

function categorizeNode(node: string) {
  if (node.includes("accept")) return "요청 접수";
  if (node.includes("structured")) return "상품데이터검색";
  if (node.includes("unstructured") || node.includes("rag")) return "리뷰데이터검색";
  if (node.includes("fusion")) return "추천종합";
  if (node.includes("final") || node.includes("respond") || node.includes("answer"))
    return "응답";
  return "추천 생성";
}

function buildStepLabel(node: string, keys: string[]) {
  if (!keys.length) return node;
  const important = keys
    .map((k) => k.replace(/_/g, " "))
    .slice(0, 3)
    .join(", ");
  return `${node} · ${important}`;
}

export default function ChatClientClassic() {
  const [sessionId, setSessionId] = useState<string>("demo-session");
  const [input, setInput] = useState<string>("");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [messageId, setMessageId] = useState<string | null>(null);

  const [finalMeta, setFinalMeta] = useState<any>(null);

  const currentAssistantIndexRef = useRef<number | null>(null);
  const [selectedStyleCodes, setSelectedStyleCodes] = useState<Set<string>>(new Set());
  const [savedStyleCodes, setSavedStyleCodes] = useState<Set<string>>(new Set());
  const [savingFeedback, setSavingFeedback] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const debugEnabled = String(process.env.NEXT_PUBLIC_API_DEBUG || "").trim() === "true";

  function debugLog(message: string, payload?: Record<string, any>) {
    if (!debugEnabled) return;
    if (payload) console.log(message, payload);
    else console.log(message);
  }

  const recommended = useMemo<Product[]>(() => {
    const list = finalMeta?.recommended_products;
    return Array.isArray(list) ? list : [];
  }, [finalMeta]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [messages, busy]);

  function toggleSelect(styleCode: string) {
    setFeedbackMsg(null);
    setSelectedStyleCodes((prev) => {
      const next = new Set(prev);
      if (next.has(styleCode)) next.delete(styleCode);
      else next.add(styleCode);
      return next;
    });
  }

  function clearSelection() {
    setSelectedStyleCodes(new Set());
    setFeedbackMsg(null);
  }

  async function saveFeedback() {
    if (!messageId) {
      setFeedbackMsg("message_id가 없습니다. 먼저 채팅을 실행해 주세요.");
      return;
    }
    const codes = Array.from(selectedStyleCodes);
    if (!codes.length) {
      setFeedbackMsg("선택된 상품이 없습니다.");
      return;
    }
    setSavingFeedback(true);
    setFeedbackMsg(null);
    try {
      debugLog("[feedback] request", {
        session_id: sessionId,
        message_id: messageId,
        selected_style_codes: codes,
      });
      const r = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message_id: messageId,
          selected_style_codes: codes,
        }),
      });
      debugLog("[feedback] response", { status: r.status, ok: r.ok });
      if (!r.ok) throw new Error(`feedback_failed: ${r.status}`);
      setSavedStyleCodes((prev) => new Set([...Array.from(prev), ...codes]));
      setFeedbackMsg(`피드백 저장 완료 (${codes.length}개)`);
      setSelectedStyleCodes(new Set());
    } catch (e: any) {
      setFeedbackMsg(`피드백 저장 실패: ${String(e?.message ?? e)}`);
    } finally {
      setSavingFeedback(false);
    }
  }

  function markAssistantDone(idx: number | null) {
    if (idx === null) return;
    setMessages((prev) => {
      const next = [...prev];
      if (!next[idx]) return prev;
      next[idx] = { ...next[idx], done: true };
      return next;
    });
  }

  async function send() {
    const q = input.trim();
    if (!q || busy) return;
    setBusy(true);
    setInput("");
    setFinalMeta(null);
    setMessageId(null);
    setSelectedStyleCodes(new Set());
    setSavedStyleCodes(new Set());
    setFeedbackMsg(null);

    setMessages((prev) => {
      const assistantIdx = prev.length + 1;
      currentAssistantIndexRef.current = assistantIdx;
      return [
        ...prev,
        { role: "user", text: q },
        { role: "assistant", text: "", steps: [], done: false, currentStage: null },
      ];
    });

    try {
      // IMPORTANT:
      // - 기본값은 Next API 프록시(`/api/chat/stream`) 사용 (Docker/배포 환경에서 안전)
      // - "직접 백엔드 호출"은 명시적으로 켠 경우에만 사용 (프록시 버퍼링 회피 목적)
      const useDirect = String(process.env.NEXT_PUBLIC_USE_DIRECT_BACKEND || "").trim() === "true";
      const directBase = useDirect ? (process.env.NEXT_PUBLIC_AGENT_BASE_URL || "").trim() : "";
      const url = directBase ? `${directBase}/v1/chat/stream` : "/api/chat/stream";
      debugLog("[chat] request", {
        url,
        session_id: sessionId,
        user_query: q,
        useDirect,
      });
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, user_query: q }),
      });
      debugLog("[chat] response", { status: res.status, ok: res.ok });
      if (!res.ok || !res.body) throw new Error(`bad_response: ${res.status}`);

      for await (const evt of parseSseStream(res.body)) {
        if (evt.event === "start") {
          const mid = evt.data?.message_id;
          if (typeof mid === "string") setMessageId(mid);
        } else if (evt.event === "state") {
          const node = String(evt.data?.node ?? "");
          const keys = Array.isArray(evt.data?.update_keys) ? evt.data.update_keys : [];
          const label = buildStepLabel(node, keys);
          const idx = currentAssistantIndexRef.current;
          if (!label || idx === null) continue;
          const category = categorizeNode(node);
          setMessages((prev) => {
            const next = [...prev];
            if (!next[idx]) return prev;
            const steps = next[idx].steps ? [...next[idx].steps] : [];
            if (!steps.some((s) => s.label === label)) steps.push({ category, label });
            next[idx] = { ...next[idx], steps, currentStage: category };
            return next;
          });
        } else if (evt.event === "token") {
          const delta = String(evt.data?.delta ?? "");
          const idx = currentAssistantIndexRef.current;
          if (idx === null) continue;
          setMessages((prev) => {
            const next = [...prev];
            if (!next[idx]) return prev;
            next[idx] = { ...next[idx], text: (next[idx].text ?? "") + delta };
            return next;
          });
        } else if (evt.event === "final") {
          setFinalMeta(evt.data);
          markAssistantDone(currentAssistantIndexRef.current);
          currentAssistantIndexRef.current = null;
        } else if (evt.event === "error") {
          const err = evt.data?.error ? String(evt.data.error) : "unknown error";
          setMessages((prev) => [...prev, { role: "assistant", text: `에러: ${err}` }]);
          markAssistantDone(currentAssistantIndexRef.current);
          currentAssistantIndexRef.current = null;
        } else if (evt.event === "done") {
          markAssistantDone(currentAssistantIndexRef.current);
          currentAssistantIndexRef.current = null;
        }
      }
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: `요청 실패: ${String(e?.message ?? e)}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid">
      <div className="panel">
        <div className="panelHeader">
          <div className="panelTitle">채팅 (스트리밍) + LangGraph 상태</div>
          <div className="pill">session: {sessionId}</div>
        </div>
        <div className="panelBody">
          <div className="row" style={{ marginBottom: 10 }}>
            <input
              className="input"
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              placeholder="session_id"
            />
          </div>

          <div className="messages chatWindow" style={{ marginBottom: 12 }}>
            {messages.length === 0 ? (
              <div className="emptyChat">
                대화를 시작해 보세요. 아래 입력창에 질문을 입력하면 스트리밍으로 답변이 표시됩니다.
              </div>
            ) : null}
            {messages.map((m, i) => {
              const hasSteps = m.role === "assistant" && (m.steps?.length ?? 0) > 0;
              const isDone = m.role === "assistant" && m.done;
              const groupedSteps = hasSteps
                ? (m.steps ?? []).reduce<Record<string, string[]>>((acc, step) => {
                    if (!acc[step.category]) acc[step.category] = [];
                    acc[step.category].push(step.label);
                    return acc;
                  }, {})
                : {};
              const visibleStages = hasSteps
                ? STAGE_ORDER.filter(
                    (stage) =>
                      (groupedSteps[stage] && groupedSteps[stage].length) ||
                      stage === m.currentStage,
                  )
                : [];
              return (
                <div key={i} className={`msgRow ${m.role}`}>
                  <div className="msgAvatar">{m.role === "user" ? "You" : "AI"}</div>
                  <div className={`msgBubble ${m.role}`}>
                    <div className="msgRole">{m.role === "user" ? "사용자" : "어시스턴트"}</div>
                    {hasSteps ? (
                      <div className="stateInline">
                        <div className="stateLabel">진행 단계</div>
                        <div className="stateGroups">
                          {visibleStages.map((category) => {
                            const items = groupedSteps[category] ?? [];
                            const isActive = !isDone && m.currentStage === category;
                            return (
                            <div key={category} className="stateGroup">
                              <div className="stateGroupHeader">
                                {isActive ? <span className="spinner" aria-hidden /> : null}
                                <span className="stateGroupTitle">{category}</span>
                              </div>
                              {items.length ? (
                                <div className="stateBadges">
                                  {items.slice(-6).map((step, idx) => (
                                    <span key={`${step}-${idx}`} className="stateBadge">
                                      {step}
                                    </span>
                                  ))}
                                </div>
                              ) : (
                                <div className="stateEmpty">대기중</div>
                              )}
                            </div>
                          );
                          })}
                        </div>
                      </div>
                    ) : null}
                    <div className="msgText">{m.text}</div>
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>

          <div className="row composer">
            <input
              className="input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") send();
              }}
              placeholder="예) 로엠 따뜻하고 편한 기모 긴팔 추천해줘"
            />
            <button className="button" onClick={send} disabled={busy}>
              {busy ? "생성중..." : "전송"}
            </button>
          </div>

          <div style={{ marginTop: 6 }} />
        </div>
      </div>

      <div className="panel">
        <div className="panelHeader">
          <div className="panelTitle">추천 상품 카드</div>
          <div className="pill">
            {finalMeta
              ? `style_codes: ${(finalMeta?.recommended_style_codes ?? []).length}`
              : "대기중"}
          </div>
        </div>
        <div className="panelBody">
          {!finalMeta ? (
            <div className="small">
              채팅을 보내면, `final` 이벤트에서 상품 메타를 받아 여기에 카드로 노출합니다.
            </div>
          ) : (
            <div>
              <div className="small">
                message_id: <code>{messageId ?? "-"}</code>
              </div>

              <div className="row" style={{ marginTop: 10, alignItems: "center" }}>
                <div className="small" style={{ flex: 1 }}>
                  선택: {selectedStyleCodes.size}개 / 저장됨: {savedStyleCodes.size}개
                </div>
                <button
                  className="button"
                  style={{ padding: "8px 10px" }}
                  onClick={clearSelection}
                  disabled={savingFeedback || selectedStyleCodes.size === 0}
                >
                  선택 초기화
                </button>
                <button
                  className="button"
                  style={{
                    padding: "8px 10px",
                    borderColor: selectedStyleCodes.size ? "rgba(52, 211, 153, 0.55)" : undefined,
                    background: selectedStyleCodes.size ? "rgba(52, 211, 153, 0.18)" : undefined,
                  }}
                  onClick={saveFeedback}
                  disabled={savingFeedback || selectedStyleCodes.size === 0}
                >
                  {savingFeedback ? "저장중..." : "피드백 저장"}
                </button>
              </div>
              {feedbackMsg ? (
                <div className="small" style={{ marginTop: 8 }}>
                  {feedbackMsg}
                </div>
              ) : null}

              {recommended.length === 0 ? (
                <div className="small" style={{ marginTop: 10 }}>
                  recommended_products 가 비어있습니다.
                </div>
              ) : (
                <div className="products">
                  {recommended.map((p, idx) => {
                    const styleCode = pick(p, "style_code", "STYLE_CODE");
                    const code = styleCode ? String(styleCode) : "";
                    const isSelected = !!code && selectedStyleCodes.has(code);
                    const isSaved = !!code && savedStyleCodes.has(code);
                    const title =
                      pick(p, "product_name", "PRODUCT_NAME") ?? "(상품명 없음)";
                    const brand = pick(p, "brand", "BRAND");
                    const price = pick(p, "price", "PRICE");
                    const material = pick(p, "material", "MATERIAL");
                    const season = pick(p, "season", "SEASON");
                    const channel = pick(p, "channel", "CHANNEL");
                    const color = pick(p, "color", "COLOR");
                    const size = pick(p, "size", "SIZE");
                    const url = pick(p, "url", "URL");
                    const imgRaw = pick(p, "image_url", "IMAGE_URL");
                    const img = imgRaw ? String(imgRaw).replace(/\?$/, "") : undefined;

                    return (
                      <div key={`${styleCode ?? "x"}-${idx}`} className="card">
                        <div className="thumb">
                          {img ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={String(img)}
                              alt={String(title)}
                              style={{
                                width: "96px",
                                height: "96px",
                                objectFit: "cover",
                              }}
                            />
                          ) : (
                            "NO IMG"
                          )}
                        </div>
                        <div className="cardBody">
                          <p className="cardTitle">{title}</p>
                          <div className="meta">
                            {brand ? <span>브랜드: {brand}</span> : null}
                            {styleCode ? <span>style_code: {styleCode}</span> : null}
                            {price ? <span>가격: {price}</span> : null}
                            {season ? <span>시즌: {season}</span> : null}
                            {channel ? <span>채널: {channel}</span> : null}
                            {color ? <span>색상: {color}</span> : null}
                            {size ? <span>사이즈: {size}</span> : null}
                            {material ? (
                              <span>소재: {String(material).slice(0, 24)}</span>
                            ) : null}
                            {isSaved ? <span style={{ color: "rgba(52, 211, 153, 0.9)" }}>저장됨</span> : null}
                            {!isSaved && isSelected ? (
                              <span style={{ color: "rgba(52, 211, 153, 0.9)" }}>선택됨</span>
                            ) : null}
                          </div>
                          <div className="linkRow">
                            {url ? (
                              <a
                                className="link"
                                href={String(url)}
                                target="_blank"
                                rel="noreferrer"
                              >
                                상품 링크
                              </a>
                            ) : (
                              <span className="small">링크 없음</span>
                            )}
                            {styleCode ? (
                              <button
                                className="button"
                                style={{
                                  padding: "8px 10px",
                                  borderColor: isSelected
                                    ? "rgba(52, 211, 153, 0.65)"
                                    : isSaved
                                      ? "rgba(124, 92, 255, 0.55)"
                                      : undefined,
                                  background: isSelected
                                    ? "rgba(52, 211, 153, 0.18)"
                                    : isSaved
                                      ? "rgba(124, 92, 255, 0.16)"
                                      : undefined,
                                }}
                                onClick={() => toggleSelect(String(styleCode))}
                                disabled={savingFeedback}
                              >
                                {isSelected ? "선택 해제" : isSaved ? "저장됨" : "선택"}
                              </button>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

