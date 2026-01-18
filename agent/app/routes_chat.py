from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, AsyncIterator, Dict, Optional

import anyio
import boto3
from botocore.config import Config as BotoConfig
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..core.config import SETTINGS
from ..core.storage import append_jsonl, chat_log_path, feedback_log_path, utc_now_iso
from ..graph.shopping_graph import GRAPH_APP
from ..utils.sse import SseEvent, chunk_text, merge_updates


router = APIRouter()


def _bedrock_model_id() -> str:
    m = SETTINGS.dspy_model
    return m[len("bedrock/") :] if m.startswith("bedrock/") else m


def _bedrock_stream_text(prompt: str) -> AsyncIterator[str]:
    """Bedrock(Anthropic) streaming. Yields text deltas."""
    # boto3 client is sync; we run it in a thread via anyio in the caller
    raise RuntimeError("use _bedrock_stream_text_sync via anyio.to_thread")


def _bedrock_stream_text_sync(prompt: str) -> list[str]:
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-northeast-2"
    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=BotoConfig(read_timeout=300, connect_timeout=10, retries={"max_attempts": 2}),
    )
    model_id = _bedrock_model_id()
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 10000,
        "temperature": 0.2,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
    }
    resp = client.invoke_model_with_response_stream(modelId=model_id, body=json.dumps(body))
    out: list[str] = []
    stream = resp.get("body")
    if stream is None:
        return out
    for event in stream:
        chunk = event.get("chunk") if isinstance(event, dict) else None
        if not chunk:
            continue
        raw = chunk.get("bytes")
        if not raw:
            continue
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        # Anthropic stream event types: message_start/content_block_start/content_block_delta/message_delta/message_stop
        if payload.get("type") == "content_block_delta":
            delta = (payload.get("delta") or {}).get("text")
            if isinstance(delta, str) and delta:
                out.append(delta)
    return out


def _bedrock_stream_to_anyio_send(prompt: str, send) -> None:
    """Run in a thread: stream Bedrock deltas into an anyio send stream."""
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-northeast-2"
    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=BotoConfig(read_timeout=300, connect_timeout=10, retries={"max_attempts": 2}),
    )
    model_id = _bedrock_model_id()
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 10000,
        "temperature": 0.2,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
    }
    try:
        resp = client.invoke_model_with_response_stream(modelId=model_id, body=json.dumps(body))
        stream = resp.get("body")
        if stream is None:
            return
        for event in stream:
            chunk = event.get("chunk") if isinstance(event, dict) else None
            if not chunk:
                continue
            raw = chunk.get("bytes")
            if not raw:
                continue
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            if payload.get("type") == "content_block_delta":
                delta = (payload.get("delta") or {}).get("text")
                if isinstance(delta, str) and delta:
                    anyio.from_thread.run(send.send, delta)
    finally:
        try:
            anyio.from_thread.run(send.aclose)
        except Exception:
            pass


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="세션 식별자(멀티턴 메모리 thread_id)")
    user_query: str = Field(..., description="사용자 채팅 입력")
    client_message_id: Optional[str] = None


@router.post("/v1/chat/stream")
async def chat_stream(req: ChatRequest):
    message_id = req.client_message_id or str(uuid.uuid4())
    started_at = time.time()

    async def event_iter() -> AsyncIterator[bytes]:
        yield SseEvent(
            event="start",
            data={"session_id": req.session_id, "message_id": message_id},
            id=message_id,
        ).encode()

        state: Dict[str, Any] = {}
        graph_input = {"user_query": req.user_query}
        config = {"configurable": {"thread_id": req.session_id}}

        llm_streamed = False
        error_obj: Optional[BaseException] = None
        llm_text_accum = ""

        try:
            async for step in GRAPH_APP.astream(graph_input, config=config, stream_mode="updates"):
                if not isinstance(step, dict) or not step:
                    continue
                for node_name, node_update in step.items():
                    if isinstance(node_update, dict):
                        merge_updates(state, node_update)
                    else:
                        state[node_name] = node_update

                    yield SseEvent(
                        event="state",
                        data={
                            "session_id": req.session_id,
                            "message_id": message_id,
                            "node": node_name,
                            "update_keys": list(node_update.keys())
                            if isinstance(node_update, dict)
                            else [],
                        },
                        id=message_id,
                    ).encode()

                    # LLM 스트리밍: graph의 composer가 prompt를 준비하면 Bedrock 스트림을 시작
                    if (not llm_streamed) and isinstance(state.get("api_response"), dict):
                        prompt = state["api_response"].get("composer_prompt")
                        if isinstance(prompt, str) and prompt.strip():
                            try:
                                send, recv = anyio.create_memory_object_stream[str](max_buffer_size=200)
                                # producer runs in background thread and pushes deltas into `send`
                                async with recv:
                                    async with anyio.create_task_group() as tg:
                                        tg.start_soon(anyio.to_thread.run_sync, _bedrock_stream_to_anyio_send, prompt, send)
                                        async for d in recv:
                                            # UI에서 "스트리밍처럼" 보이도록 delta를 잘게 쪼개고 약간의 딜레이를 둡니다.
                                            # (Bedrock이 큰 덩어리로 빠르게 반환하면 한 번에 보이는 것처럼 느껴질 수 있음)
                                            step = max(int(SETTINGS.stream_chunk_chars), 1)
                                            for i in range(0, len(d), step):
                                                piece = d[i : i + step]
                                                llm_text_accum += piece
                                                yield SseEvent(
                                                    event="token",
                                                    data={
                                                        "session_id": req.session_id,
                                                        "message_id": message_id,
                                                        "delta": piece,
                                                    },
                                                    id=message_id,
                                                ).encode()
                                                if SETTINGS.stream_delay_ms > 0:
                                                    await anyio.sleep(SETTINGS.stream_delay_ms / 1000.0)
                                # best-effort close send stream after consumption
                                try:
                                    await send.aclose()
                                except Exception:
                                    pass
                            except Exception:
                                # fallback: 스트리밍 실패 시, 빈 응답 방지용(간단 chunk)
                                fallback_text = "추천을 생성하는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
                                async for piece in chunk_text(
                                    fallback_text, SETTINGS.stream_chunk_chars
                                ):
                                    llm_text_accum += piece
                                    yield SseEvent(
                                        event="token",
                                        data={
                                            "session_id": req.session_id,
                                            "message_id": message_id,
                                            "delta": piece,
                                        },
                                        id=message_id,
                                    ).encode()
                            llm_streamed = True
        except Exception as e:
            error_obj = e
            yield SseEvent(
                event="error",
                data={
                    "session_id": req.session_id,
                    "message_id": message_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                id=message_id,
            ).encode()
        finally:
            api_response = (
                state.get("api_response") if isinstance(state.get("api_response"), dict) else {}
            )
            try:
                structured_products = state.get("structured_data", [])
                if not isinstance(structured_products, list):
                    structured_products = []
                slim_products = []
                for p in structured_products[:50]:
                    if not isinstance(p, dict):
                        continue
                    slim_products.append(
                        {
                            "style_code": p.get("style_code") or p.get("STYLE_CODE"),
                            "brand": p.get("brand"),
                            "category": p.get("category"),
                            "subcategory": p.get("subcategory"),
                            "product_name": p.get("product_name"),
                            "material": p.get("material"),
                            "price": p.get("price"),
                            "url": p.get("url"),
                        }
                    )
                append_jsonl(
                    chat_log_path(),
                    {
                        "ts": utc_now_iso(),
                        "session_id": req.session_id,
                        "message_id": message_id,
                        "user_query": req.user_query,
                        "elapsed_ms": int((time.time() - started_at) * 1000),
                        "error": str(error_obj) if error_obj else None,
                        "error_type": type(error_obj).__name__ if error_obj else None,
                        "structured": {
                            "constraints_used": state.get("structured_constraints_used"),
                            "constraints_attempts": state.get("structured_constraints_attempts", []),
                            "fallback_used": state.get("structured_fallback_used", False),
                            "sql": state.get("structured_sql"),
                            "rows_count": len(structured_products),
                        },
                        "structured_products": slim_products,
                        "unstructured": {
                            "review_style_codes": state.get("unstructured_style_codes", []),
                            "review_summary": state.get("unstructured_reviews_summary", ""),
                        },
                        "recommended_style_codes": api_response.get("recommended_style_codes", []),
                        "recommended_products_count": len(
                            api_response.get("recommended_products", []) or []
                        ),
                    },
                )
            except Exception:
                pass

        if error_obj is not None:
            yield SseEvent(
                event="done",
                data={"session_id": req.session_id, "message_id": message_id},
                id=message_id,
            ).encode()
            return

        # 멀티턴 메모리 저장: assistant 메시지를 thread_id 상태에 반영
        try:
            messages = list(state.get("messages", []))
            if llm_text_accum:
                messages.append({"role": "assistant", "content": llm_text_accum})
                await GRAPH_APP.aupdate_state(
                    config,
                    {
                        "messages": messages,
                        "llm_text": llm_text_accum,
                        "final_response": llm_text_accum,
                    },
                )
        except Exception:
            pass

        yield SseEvent(
            event="final",
            data={
                "session_id": req.session_id,
                "message_id": message_id,
                "elapsed_ms": int((time.time() - started_at) * 1000),
                "recommended_products": api_response.get("recommended_products", []),
                "grouped_recommended_products": api_response.get("grouped_recommended_products", {}),
                "recommended_style_codes": api_response.get("recommended_style_codes", []),
            },
            id=message_id,
        ).encode()

        yield SseEvent(
            event="done",
            data={"session_id": req.session_id, "message_id": message_id},
            id=message_id,
        ).encode()

    return StreamingResponse(
        event_iter(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str
    rating: Optional[int] = Field(default=None, description="1~5")
    selected_style_codes: Optional[list[str]] = Field(default=None)
    notes: Optional[str] = None


@router.post("/v1/feedback")
async def feedback(req: FeedbackRequest) -> dict:
    append_jsonl(
        feedback_log_path(),
        {
            "ts": utc_now_iso(),
            "session_id": req.session_id,
            "message_id": req.message_id,
            "rating": req.rating,
            "selected_style_codes": req.selected_style_codes or [],
            "notes": req.notes,
        },
    )
    return {"ok": True}

