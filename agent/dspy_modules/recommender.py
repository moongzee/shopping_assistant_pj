from __future__ import annotations

import json
from typing import Any, List

import dspy
from pydantic import BaseModel, Field


def _safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


class RelaxedConstraintsResult(BaseModel):
    candidates: List[str] = Field(default_factory=list)
    notes: str = Field(default="", description="생성 근거/주의사항(디버그용)")


class RelaxedConstraintsSignature(dspy.Signature):
    user_query = dspy.InputField(desc="사용자 원문 질문")
    strict_constraints = dspy.InputField(desc="현재 정형검색 제약(결과 0개 가능)")
    brand_hint = dspy.InputField(desc="추출된 브랜드 힌트(없으면 빈 문자열)")
    candidates: RelaxedConstraintsResult = dspy.OutputField(desc="완화된 정형검색 제약 후보")


class RelaxedConstraintsGenerator(dspy.Module):
    def __init__(self):
        super().__init__()
        self.prog = dspy.ChainOfThought(RelaxedConstraintsSignature)

    def forward(self, user_query: str, strict_constraints: str, brand_hint: str = ""):
        return self.prog(
            user_query=user_query,
            strict_constraints=strict_constraints,
            brand_hint=brand_hint,
        )


class DecisionResult(BaseModel):
    recommended_style_codes: List[str] = Field(default_factory=list, max_length=30)
    reason_bullets: List[str] = Field(default_factory=list)
    caveats: List[str] = Field(default_factory=list)


class FusionDecisionSignature(dspy.Signature):
    user_query = dspy.InputField(desc="사용자 질문")
    conversation_history = dspy.InputField(desc="멀티턴 히스토리(없으면 빈 문자열)")
    products_json = dspy.InputField(desc="상품 후보 목록(JSON list)")
    reviews_summary = dspy.InputField(desc="리뷰 요약 텍스트(없으면 빈 문자열)")
    review_style_codes_json = dspy.InputField(desc="리뷰 style_code 후보(JSON list)")
    decision: DecisionResult = dspy.OutputField(desc="추천 style_code + 근거/주의사항")


class FusionDecisionMaker(dspy.Module):
    def __init__(self):
        super().__init__()
        self.prog = dspy.ChainOfThought(FusionDecisionSignature)

    def forward(
        self,
        user_query: str,
        conversation_history: str,
        products: List[dict],
        reviews_summary: str,
        review_style_codes: List[str],
    ):
        return self.prog(
            user_query=user_query,
            conversation_history=conversation_history or "",
            products_json=json.dumps(products, ensure_ascii=False),
            reviews_summary=reviews_summary or "",
            review_style_codes_json=json.dumps(review_style_codes, ensure_ascii=False),
        )


class RankingResult(BaseModel):
    recommended_style_codes: List[str] = Field(default_factory=list, description="우선순위 순")


class ProductRankerSignature(dspy.Signature):
    user_query = dspy.InputField(desc="사용자 질문")
    conversation_history = dspy.InputField(desc="멀티턴 히스토리(없으면 빈 문자열)")
    products_json = dspy.InputField(desc="상품 후보 목록(JSON list)")
    recommended_style_codes: RankingResult = dspy.OutputField(desc="추천 style_code 순서")


class ProductRanker(dspy.Module):
    def __init__(self):
        super().__init__()
        self.prog = dspy.ChainOfThought(ProductRankerSignature)

    def forward(self, user_query: str, conversation_history: str, products: List[dict]):
        return self.prog(
            user_query=user_query,
            conversation_history=conversation_history or "",
            products_json=json.dumps(products, ensure_ascii=False),
        )


def coerce_relaxed_candidates(raw_prediction: Any) -> List[str]:
    try:
        obj = raw_prediction.candidates
    except Exception:
        return []

    if isinstance(obj, dict):
        obj = _safe_json_loads(json.dumps(obj, ensure_ascii=False))

    if hasattr(obj, "candidates"):
        obj = getattr(obj, "candidates", [])

    if isinstance(obj, list):
        out: List[str] = []
        for c in obj:
            if isinstance(c, str):
                s = " ".join(c.split()).strip()
                if s and s not in out:
                    out.append(s)
        return out
    return []

