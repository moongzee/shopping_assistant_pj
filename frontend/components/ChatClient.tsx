"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
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

export default function ChatClient() {
  const [sessionId, setSessionId] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return sessionStorage.getItem("chat-session-id") || "demo-session";
    }
    return "demo-session";
  });
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
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  
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
    if (messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages, busy]);

  // 세션 스토리지에 세션 ID 저장
  useEffect(() => {
    if (typeof window !== "undefined") {
      sessionStorage.setItem("chat-session-id", sessionId);
    }
  }, [sessionId]);

  // Textarea 자동 높이 조절
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

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
      const useDirect = String(process.env.NEXT_PUBLIC_USE_DIRECT_BACKEND || "").trim() === "true";
      const directBase = useDirect ? (process.env.NEXT_PUBLIC_AGENT_BASE_URL || "").trim() : "";
      const url = directBase ? `${directBase}/v1/chat/stream` : "/api/chat/stream";
      
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, user_query: q }),
      });
      
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

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const isInitial = messages.length === 0;

  return (
    <div className="grid">
      <div className={`chatPanel ${isInitial ? "centered" : ""}`}>
        {!isInitial && (
          <div className="panelHeader">
            <div className="panelTitle">AI 쇼핑 분석</div>
            <div className="pill">ID: {sessionId}</div>
          </div>
        )}
        
        <div className="chatWindow">
          {isInitial ? (
            <div className="emptyChat">
              <h2 style={{ fontSize: "32px", fontWeight: 700, marginBottom: "16px" }}>무엇을 도와드릴까요?</h2>
              <p style={{ color: "var(--muted)", fontSize: "16px" }}>궁금한 스타일이나 상품을 물어보세요.</p>
            </div>
          ) : (
            <div className="messages">
              {messages.map((m, i) => {
                const hasSteps = m.role === "assistant" && (m.steps?.length ?? 0) > 0;
                const isDone = m.role === "assistant" && m.done;
                const groupedSteps = hasSteps ? (m.steps ?? []).reduce<Record<string, string[]>>((acc, step) => {
                  if (!acc[step.category]) acc[step.category] = [];
                  acc[step.category].push(step.label);
                  return acc;
                }, {}) : {};
                const visibleStages = hasSteps ? STAGE_ORDER.filter(s => groupedSteps[s] || s === m.currentStage) : [];
                
                return (
                  <div key={i} className={`msgRow ${m.role}`}>
                    <div className="msgAvatar">{m.role === "user" ? "You" : "AI"}</div>
                    <div className={`msgBubble ${m.role}`}>
                      <div className="msgRole">{m.role === "user" ? "나" : "쇼핑 어시스턴트"}</div>
                      {hasSteps && (
                        <div className="stateInline">
                          <div className="stateGroups">
                            {visibleStages.map(cat => (
                              <div key={cat} className="stateGroup">
                                <div className="stateGroupHeader">
                                  {!isDone && m.currentStage === cat && <span className="spinner" />}
                                  <span className="stateGroupTitle">{cat}</span>
                                </div>
                                <div className="stateBadges">
                                  {(groupedSteps[cat] || []).map((s, idx) => <span key={idx} className="stateBadge">{s}</span>)}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      <div className="msgText">{m.text}</div>
                    </div>
                  </div>
                );
              })}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <div className="composerWrapper">
          <div className="composer">
            <textarea ref={textareaRef} className="textarea" rows={1} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown} placeholder="어떤 상품을 찾으시나요?" />
            <button className="button" onClick={send} disabled={busy}>
              {busy ? (
                "..."
              ) : (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>

      {!isInitial && (
        <div className="panel productPanel">
          <div className="panelHeader">
            <div className="panelTitle">맞춤 추천 상품</div>
            <div className="pill">{recommended.length}개</div>
          </div>
          <div className="panelBody" style={{ overflowY: "auto" }}>
            {finalMeta ? (
              <div className="products">
                {recommended.map((p, idx) => {
                  const code = pick(p, "style_code", "STYLE_CODE") || "";
                  const img = pick(p, "image_url", "IMAGE_URL")?.replace(/\?$/, "");
                  return (
                    <div key={idx} className="card">
                      <div className="thumb">{img ? <img src={img} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : "NO IMG"}</div>
                      <div className="cardBody">
                        <p className="cardTitle">{pick(p, "product_name", "PRODUCT_NAME")}</p>
                        <div className="linkRow">
                          <span className="small">{code}</span>
                          <button className="button" style={{ padding: "4px 8px", fontSize: "11px" }} onClick={() => toggleSelect(String(code))}>
                            {selectedStyleCodes.has(String(code)) ? "해제" : savedStyleCodes.has(String(code)) ? "저장됨" : "선택"}
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : <div className="small" style={{ textAlign: "center", padding: "20px" }}>상품을 분석 중입니다...</div>}
          </div>
        </div>
      )}
    </div>
  );
}
