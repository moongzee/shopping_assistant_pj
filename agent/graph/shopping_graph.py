from __future__ import annotations

import json
import re
from typing import Any, Dict, List, NotRequired, TypedDict

import anyio
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from ..core.artifacts import (
    get_fusion_decision_maker,
    get_product_ranker,
    get_relaxed_constraints_generator,
)
from ..core.config import SETTINGS
from ..dspy_modules.intent import IntentAnalysisAgent, ensure_dspy_configured
from ..dspy_modules.recommender import coerce_relaxed_candidates
from ..integrations.mcp_tools import execute_cortex_analyst_sql, execute_cortex_search_rag


class ChatMessage(TypedDict):
    role: str  # "user" | "assistant" | "system"
    content: str


class ShoppingState(TypedDict):
    # 입력
    user_query: str
    structured_query: NotRequired[str]

    # 멀티턴 히스토리 (세션별 체크포인터에 저장됨)
    messages: NotRequired[List[ChatMessage]]

    # Intent
    sql_constraints: str
    rag_keywords: str

    # Structured (Cortex Analyst)
    structured_columns: NotRequired[List[str]]
    structured_sql: NotRequired[str]
    structured_result_text: NotRequired[str]
    structured_data: List[dict]
    structured_style_codes: NotRequired[List[str]]
    structured_constraints_used: NotRequired[str]
    structured_fallback_used: NotRequired[bool]
    structured_constraints_attempts: NotRequired[List[str]]

    # Unstructured (Cortex Search)
    cortex_service_name: str
    cortex_database_name: str
    cortex_schema_name: str
    cortex_columns: List[str]
    unstructured_data: List[dict]
    unstructured_style_codes: NotRequired[List[str]]
    unstructured_reviews_summary: NotRequired[str]

    # Fusion output ("결정"만: 텍스트 금지)
    fusion_decision: NotRequired[dict]
    recommended_style_codes: NotRequired[List[str]]
    recommended_products: NotRequired[List[dict]]

    # Composer output ("표현"만)
    llm_text: NotRequired[str]

    # 최종 응답(기존 호환용: llm_text를 그대로 넣음)
    final_response: str

    # API용 최종 payload (LLM 텍스트 + 상품 메타 분리)
    api_response: NotRequired[dict]


def _format_history(messages: List[ChatMessage], max_turns: int) -> str:
    if not messages:
        return ""
    trimmed = messages[-(max_turns * 2) :]
    lines: List[str] = []
    for m in trimmed:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"사용자: {content}")
        elif role == "assistant":
            lines.append(f"어시스턴트: {content}")
        else:
            lines.append(f"{role}: {content}")
    return "\n".join(lines).strip()


def _pick_products_by_style_codes(products: List[dict], style_codes: List[str]) -> List[dict]:
    if not style_codes:
        return []
    by_code: Dict[str, dict] = {}
    for p in products:
        if not isinstance(p, dict):
            continue
        code = p.get("style_code") or p.get("STYLE_CODE")
        if isinstance(code, str) and code and code not in by_code:
            by_code[code] = p
    picked: List[dict] = []
    for code in style_codes:
        p = by_code.get(code)
        if p:
            picked.append(p)
    return picked


def _fallback_recommend_products(products: List[dict], k: int = 30) -> List[dict]:
    return [p for p in products if isinstance(p, dict)][:k]


async def intent_analysis_node(state: ShoppingState) -> dict:
    ensure_dspy_configured()
    user_query = state["user_query"]
    messages = list(state.get("messages", []))
    messages.append({"role": "user", "content": user_query})

    history_text = _format_history(messages[:-1], SETTINGS.memory_max_turns)
    intent_query = state.get("structured_query") or user_query
    if history_text:
        intent_query = f"대화 히스토리:\n{history_text}\n\n사용자 질문:\n{intent_query}"

    dspy_agent = IntentAnalysisAgent()
    prediction = await anyio.to_thread.run_sync(dspy_agent, intent_query)
    intent = prediction.intent
    return {
        "messages": messages,
        "sql_constraints": intent.sql_constraints,
        "rag_keywords": intent.rag_keywords,
    }


async def structured_query_node(state: ShoppingState) -> dict:
    constraints = state.get("sql_constraints")
    if not constraints:
        raise ValueError("sql_constraints is required for the structured query node")

    base = str(constraints).strip()
    user_query = str(state.get("user_query", "")).strip()

    def extract_brand(text: str) -> str | None:
        m = re.search(r"([가-힣A-Za-z0-9_]+)\s*브랜드", text)
        if m:
            v = m.group(1)
            return v if v and v not in {"의", "가", "는"} else None
        m = re.search(r"브랜드(?:가|는)?\s*([가-힣A-Za-z0-9_]+)", text)
        if m:
            v = m.group(1)
            return v if v and v not in {"의", "가", "는"} else None
        return None

    async def _generate_relaxed_candidates(brand_hint: str | None) -> List[str]:
        ensure_dspy_configured()
        generator = get_relaxed_constraints_generator()
        pred = await anyio.to_thread.run_sync(generator, user_query, base, brand_hint or "")
        return coerce_relaxed_candidates(pred)

    brand_hint = extract_brand(base) or extract_brand(user_query)

    attempts: List[str] = [base] if base else []
    success_constraints: str | None = None

    analyst_result = await execute_cortex_analyst_sql(base)
    if analyst_result.get("rows"):
        success_constraints = base

    if not analyst_result.get("rows"):
        for cand in await _generate_relaxed_candidates(brand_hint):
            if cand in attempts:
                continue
            attempts.append(cand)
            r = await execute_cortex_analyst_sql(cand)
            if r.get("rows"):
                analyst_result = r
                success_constraints = cand
                break

    # 최소 안전장치
    if not analyst_result.get("rows"):
        rule_candidates: List[str] = []
        if "기모" in base:
            rule_candidates.append(re.sub(r"\s+", " ", base.replace("기모", " ")).strip())
        if "소재" in base:
            rule_candidates.append(re.sub(r"\s+", " ", base.replace("소재", " ")).strip())
        for cand in rule_candidates:
            if not cand or cand in attempts:
                continue
            attempts.append(cand)
            r = await execute_cortex_analyst_sql(cand)
            if r.get("rows"):
                analyst_result = r
                success_constraints = cand
                break

    if not analyst_result.get("rows"):
        if brand_hint:
            cand = f"{brand_hint} 브랜드 제품"
            if cand not in attempts:
                attempts.append(cand)
                r = await execute_cortex_analyst_sql(cand)
                if r.get("rows"):
                    analyst_result = r
                    success_constraints = cand

    if (not analyst_result.get("rows")) and user_query and (user_query not in attempts):
        attempts.append(user_query)
        analyst_result = await execute_cortex_analyst_sql(user_query)
        if analyst_result.get("rows"):
            success_constraints = user_query

    used_constraints = success_constraints or (attempts[-1] if attempts else base)
    fallback_used = bool(success_constraints and attempts and used_constraints != attempts[0])
    return {
        "structured_data": analyst_result.get("rows", []),
        "structured_columns": analyst_result.get("columns", []),
        "structured_style_codes": analyst_result.get("style_codes", []),
        "structured_sql": analyst_result.get("sql"),
        "structured_result_text": analyst_result.get("result_text"),
        "structured_constraints_used": used_constraints,
        "structured_fallback_used": fallback_used,
        "structured_constraints_attempts": attempts,
    }


async def unstructured_query_node(state: ShoppingState) -> dict:
    keywords = state["rag_keywords"]
    service_name = state.get("cortex_service_name", SETTINGS.mcp_cortex_search_service_name)
    database_name = state.get("cortex_database_name", SETTINGS.mcp_cortex_search_database_name)
    schema_name = state.get("cortex_schema_name", SETTINGS.mcp_cortex_search_schema_name)
    columns = state.get("cortex_columns", SETTINGS.mcp_cortex_search_columns)
    structured_codes = state.get("structured_style_codes", [])

    results = await execute_cortex_search_rag(
        keywords,
        service_name=service_name,
        database_name=database_name,
        schema_name=schema_name,
        columns=columns,
        style_code_filter=structured_codes,
    )
    return {
        "unstructured_data": results.get("rows", []),
        "unstructured_style_codes": results.get("style_codes", []),
        "unstructured_reviews_summary": results.get("review_summary", ""),
    }


async def result_fusion_node(state: ShoppingState) -> dict:
    ensure_dspy_configured()
    products = state.get("structured_data", [])
    query = state["user_query"]
    reviews_summary = state.get("unstructured_reviews_summary", "")
    review_style_codes = state.get("unstructured_style_codes", [])
    history_text = _format_history(state.get("messages", []), SETTINGS.memory_max_turns)

    maker = get_fusion_decision_maker()
    pred = await anyio.to_thread.run_sync(
        maker,
        query,
        history_text or "",
        products,
        reviews_summary or "",
        review_style_codes or [],
    )
    decision_obj = getattr(pred, "decision", None)
    rec_codes = getattr(decision_obj, "recommended_style_codes", None)

    if not isinstance(rec_codes, list) or not rec_codes:
        product_codes: List[str] = []
        for p in products:
            if not isinstance(p, dict):
                continue
            code = p.get("style_code") or p.get("STYLE_CODE")
            if isinstance(code, str) and code:
                product_codes.append(code)
        inter = [c for c in review_style_codes if c in set(product_codes)]
        rec_codes = inter[:30] if inter else product_codes[:30]

    rec_codes = [c for c in rec_codes if isinstance(c, str) and c]
    rec_products = _pick_products_by_style_codes(products, rec_codes)
    return {
        "fusion_decision": {
            "recommended_style_codes": rec_codes,
            "reason_bullets": getattr(decision_obj, "reason_bullets", []) or [],
            "caveats": getattr(decision_obj, "caveats", []) or [],
        },
        "recommended_style_codes": rec_codes,
        "recommended_products": rec_products,
    }


async def response_composer_node(state: ShoppingState) -> dict:
    ensure_dspy_configured()
    query = state["user_query"]
    products = state.get("structured_data", [])

    rec_products = state.get("recommended_products", [])
    if not rec_products and products:
        history_text = _format_history(state.get("messages", []), SETTINGS.memory_max_turns)
        ranker = get_product_ranker()
        pred = await anyio.to_thread.run_sync(ranker, query, history_text or "", products)
        ranked = getattr(pred, "recommended_style_codes", None)
        codes = getattr(ranked, "recommended_style_codes", None) if ranked is not None else None
        if isinstance(codes, list) and codes:
            codes = [c for c in codes if isinstance(c, str) and c][:30]
            rec_products = _pick_products_by_style_codes(products, codes)
        if not rec_products:
            rec_products = _fallback_recommend_products(products, k=30)

    decision = state.get("fusion_decision", {})

    grouped: dict[str, List[dict]] = {}
    category_order: List[str] = []
    for p in rec_products:
        if not isinstance(p, dict):
            continue
        cat = p.get("category") or p.get("subcategory") or "기타"
        cat = str(cat)
        if cat not in grouped:
            grouped[cat] = []
            category_order.append(cat)
        grouped[cat].append(p)
    grouped_recommended_products = {cat: grouped[cat] for cat in category_order}

    history_text = _format_history(state.get("messages", []), SETTINGS.memory_max_turns)
    prompt = f"""
[대화 히스토리]
{history_text or "없음"}

사용자 질문: {query}

아래는 추천 결정 결과다(구조화):
{decision}

아래는 추천 상품(카테고리별 그룹)이다:
{grouped_recommended_products}

요청:
- 한국어로, 사용자 질문에 맞는 '패션 의류 쇼핑 추천' 답변을 작성해라.
- 반드시 카테고리별 섹션(예: '상의', '아우터', '바지' 등)으로 나눠서 작성해라.
- 각 섹션에서 상위 추천부터 보여줘라.
- 추천은 총 최대 30개까지 가능하나, 너무 길어지면 카테고리별로 '상세 3~5개 + 나머지 간단 나열' 방식으로 요약해라.
- 각 상품의 상세 표기는 가능한 한 (상품명, 가격, 색상, 사이즈, 소재/특징 1줄, 링크(url))을 포함해라.
- 사용자의 의도가 불명확하면, 마지막에 선택 질문 1~2개(예: 핏/예산/사용상황)를 짧게 추가해라.
""".strip()

    derived_rec_codes: List[str] = []
    for p in rec_products:
        if not isinstance(p, dict):
            continue
        code = p.get("style_code") or p.get("STYLE_CODE")
        if isinstance(code, str) and code:
            derived_rec_codes.append(code)

    # NOTE:
    # LLM 최종 답변 생성/스트리밍은 API 레이어(routes_chat.py)에서 Bedrock 스트리밍으로 수행합니다.
    # 그래프는 카드 렌더링용 메타 + 프롬프트만 준비합니다.
    api_response = {
        "recommended_products": rec_products,
        "grouped_recommended_products": grouped_recommended_products,
        "recommended_style_codes": derived_rec_codes,
        "composer_prompt": prompt,
    }

    return {"api_response": api_response}


def build_graph():
    workflow = StateGraph(ShoppingState)
    workflow.add_node("intent_agent", intent_analysis_node)
    workflow.add_node("structured_agent", structured_query_node)
    workflow.add_node("unstructured_agent", unstructured_query_node)
    workflow.add_node("fusion_agent", result_fusion_node)
    workflow.add_node("composer", response_composer_node)

    workflow.set_entry_point("intent_agent")
    workflow.add_edge("intent_agent", "structured_agent")
    workflow.add_edge("structured_agent", "unstructured_agent")
    workflow.add_edge("unstructured_agent", "fusion_agent")
    workflow.add_edge("fusion_agent", "composer")
    workflow.add_edge("composer", END)

    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


GRAPH_APP = build_graph()

