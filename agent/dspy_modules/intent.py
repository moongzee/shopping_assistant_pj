from __future__ import annotations

from typing import Optional

import dspy
from pydantic import BaseModel, Field

from ..core.config import SETTINGS


class QueryIntent(BaseModel):
    sql_constraints: str = Field(
        ...,
        description="가격, 브랜드, 색상, 사이즈 등 DB 컬럼으로 필터링 가능한 조건의 정형 키워드를 한문장으로 표현",
    )
    rag_keywords: str = Field(
        ...,
        description="분위기, 착용감, 후기, 용도 등 리뷰나 설명에서 찾아야 하는 비정형 키워드를 한문장으로 표현",
    )
    reasoning: str = Field(..., description="왜 이렇게 분리했는지에 대한 짧은 추론")


class IntentSplitter(dspy.Signature):
    """사용자의 쇼핑 질의를 정형(SQL)과 비정형(RAG)으로 분리."""

    user_query = dspy.InputField(desc="사용자의 자연어 쇼핑 요청")
    intent: QueryIntent = dspy.OutputField(desc="분리된 검색 의도")


class IntentAnalysisAgent(dspy.Module):
    def __init__(self):
        super().__init__()
        self.prog = dspy.ChainOfThought(IntentSplitter)

    def forward(self, user_query: str):
        return self.prog(user_query=user_query)


_CONFIGURED = False


def ensure_dspy_configured(model: Optional[str] = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    lm = dspy.LM(model=(model or SETTINGS.dspy_model))
    dspy.configure(lm=lm)
    _CONFIGURED = True

