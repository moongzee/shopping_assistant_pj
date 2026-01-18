"use client";

import { useMemo, useRef, useState } from "react";
import { parseSseStream } from "@/lib/sse";

type ChatMsg = { role: "user" | "assistant"; text: string };

type Product = Record<string, any>;

function pick(v: any, ...keys: string[]) {
  for (const k of keys) {
    const val = v?.[k];
    if (val !== undefined && val !== null && String(val).trim() !== "") return val;
  }
  return undefined;
}

export default function ChatClient() {
  const [sessionId, setSessionId] = useState<string>("demo-session");
  const [input, setInput] = useState<string>("");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [messageId, setMessageId] = useState<string | null>(null);

  const [states, setStates] = useState<{ node: string; update_keys: string[] }[]>([]);
  const [finalMeta, setFinalMeta] = useState<any>(null);

  const currentAssistantIndexRef = useRef<number | null>(null);
  const [selectedStyleCodes, setSelectedStyleCodes] = useState<Set<string>>(new Set());
  const [savedStyleCodes, setSavedStyleCodes] = useState<Set<string>>(new Set());
  const [savingFeedback, setSavingFeedback] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);

  const grouped = useMemo<Record<string, Product[]>>(() => {
    const g = finalMeta?.grouped_recommended_products;
    if (g && typeof g === "object") return g;
    const list = finalMeta?.recommended_products;
    if (Array.isArray(list)) {
      const by: Record<string, Product[]> = {};
      for (const p of list) {
        if (!p || typeof p !== "object") continue;
        const cat = String(pick(p, "category", "subcategory") ?? "기타");
        if (!by[cat]) by[cat] = [];
        by[cat].push(p);
      }
      return by;
    }
    return {};
  }, [finalMeta]);

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

  async function send() {
    const q = input.trim();
    if (!q || busy) return;
    setBusy(true);
    setInput("");
    setFinalMeta(null);
    setStates([]);
    setMessageId(null);
    setSelectedStyleCodes(new Set());
    setSavedStyleCodes(new Set());
    setFeedbackMsg(null);

    setMessages((prev) => {
      const assistantIdx = prev.length + 1;
      currentAssistantIndexRef.current = assistantIdx;
      return [...prev, { role: "user", text: q }, { role: "assistant", text: "" }];
    });

    try {
      const directBase = (process.env.NEXT_PUBLIC_AGENT_BASE_URL || "").trim();
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
          if (node) setStates((prev) => [...prev, { node, update_keys: keys }]);
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
        } else if (evt.event === "error") {
          const err = evt.data?.error ? String(evt.data.error) : "unknown error";
          setMessages((prev) => [...prev, { role: "assistant", text: `에러: ${err}` }]);
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

          <div className="messages" style={{ marginBottom: 12 }}>
            {messages.map((m, i) => (
              <div key={i} className="msg">
                <div className="msgRole">{m.role}</div>
                <div className="msgText">{m.text}</div>
              </div>
            ))}
          </div>

          <div className="row">
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

          <div style={{ marginTop: 14 }}>
            <div className="small" style={{ marginBottom: 8 }}>
              진행 상태 (최신 순): {states.length} events
            </div>
            <div className="statusList">
              {states
                .slice(-12)
                .reverse()
                .map((s, idx) => (
                  <span key={idx} className="badge">
                    {s.node}
                  </span>
                ))}
            </div>
          </div>
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

              {Object.keys(grouped).length === 0 ? (
                <div className="small" style={{ marginTop: 10 }}>
                  grouped_recommended_products 가 비어있습니다.
                </div>
              ) : (
                <div className="products">
                  {Object.entries(grouped).map(([cat, items]) => (
                    <div key={cat}>
                      <div className="groupTitle">{cat}</div>
                      {items.map((p, idx) => {
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
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

