from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import dspy
import httpx

from ..core.config import SETTINGS
from ..dspy_modules.intent import IntentAnalysisAgent, ensure_dspy_configured
from ..dspy_modules.recommender import FusionDecisionMaker, ProductRanker, RelaxedConstraintsGenerator


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def compile_relaxed_constraints(dataset_path: Path, out_path: Path) -> None:
    ensure_dspy_configured()

    rows = read_jsonl(dataset_path)
    examples: List[dspy.Example] = []
    for r in rows:
        label = r.get("label_candidates", [])
        # label은 RelaxedConstraintsResult 형태로 매핑
        examples.append(
            dspy.Example(
                user_query=r.get("user_query", ""),
                strict_constraints=r.get("strict_constraints", ""),
                brand_hint=r.get("brand_hint", ""),
                candidates={"candidates": label, "notes": ""},
            ).with_inputs("user_query", "strict_constraints", "brand_hint")
        )

    program = RelaxedConstraintsGenerator()
    if len(examples) < 2:
        raise ValueError(
            "Dataset too small. Need at least 2 examples to compile. "
            "Collect more logs/feedback first."
        )

    # MIPROv2가 있으면 우선 사용
    tele = getattr(dspy.teleprompt, "MIPROv2", None)
    if tele is None:
        tele = dspy.teleprompt.BootstrapFewShotWithRandomSearch
        optimizer = tele(max_bootstrapped_demos=6, num_candidate_programs=8)
    else:
        # MIPROv2는 valset이 없으면 trainset >= 2 필요(이미 체크)
        optimizer = tele(metric=None, max_bootstrapped_demos=6, num_threads=1)

    compiled = optimizer.compile(program, trainset=examples)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compiled.save(str(out_path))
    print("saved", out_path)


def _hit_rate(pred_codes: Any, label_codes: List[str], k: int = 10) -> float:
    if not isinstance(label_codes, list):
        return 0.0
    label = [c for c in label_codes if isinstance(c, str) and c]
    if not label:
        return 0.0
    if not isinstance(pred_codes, list):
        return 0.0
    pred = [c for c in pred_codes if isinstance(c, str) and c][:k]
    if not pred:
        return 0.0
    return 1.0 if any(c in set(pred) for c in label) else 0.0


def compile_product_ranker(dataset_path: Path, out_path: Path) -> None:
    ensure_dspy_configured()
    rows = read_jsonl(dataset_path)
    examples: List[dspy.Example] = []
    for r in rows:
        examples.append(
            dspy.Example(
                user_query=r.get("user_query", ""),
                conversation_history=r.get("conversation_history", ""),
                products_json=r.get("products_json", "[]"),
                recommended_style_codes={
                    "recommended_style_codes": r.get("label_style_codes", []),
                },
            ).with_inputs("user_query", "conversation_history", "products_json")
        )
    if len(examples) < 2:
        raise ValueError("Need at least 2 ranker examples to compile.")

    program = ProductRanker()

    def metric(example, pred, trace=None):
        # pred.recommended_style_codes.recommended_style_codes
        out = getattr(getattr(pred, "recommended_style_codes", None), "recommended_style_codes", None)
        label = getattr(example, "recommended_style_codes", {}).get("recommended_style_codes", [])
        return _hit_rate(out, label, k=10)

    optimizer = dspy.teleprompt.BootstrapFewShotWithRandomSearch(
        metric=metric, max_bootstrapped_demos=6, num_candidate_programs=8
    )
    compiled = optimizer.compile(program, trainset=examples)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compiled.save(str(out_path))
    print("saved", out_path)


def compile_fusion_decision(dataset_path: Path, out_path: Path) -> None:
    ensure_dspy_configured()
    rows = read_jsonl(dataset_path)
    examples: List[dspy.Example] = []
    for r in rows:
        examples.append(
            dspy.Example(
                user_query=r.get("user_query", ""),
                conversation_history=r.get("conversation_history", ""),
                products_json=r.get("products_json", "[]"),
                reviews_summary=r.get("reviews_summary", ""),
                review_style_codes_json=r.get("review_style_codes_json", "[]"),
                decision={
                    "recommended_style_codes": r.get("label_style_codes", []),
                    "reason_bullets": [],
                    "caveats": [],
                },
            ).with_inputs(
                "user_query",
                "conversation_history",
                "products_json",
                "reviews_summary",
                "review_style_codes_json",
            )
        )
    if len(examples) < 2:
        raise ValueError("Need at least 2 fusion examples to compile.")

    program = FusionDecisionMaker()

    def metric(example, pred, trace=None):
        out = getattr(getattr(pred, "decision", None), "recommended_style_codes", None)
        label = getattr(example, "decision", {}).get("recommended_style_codes", [])
        return _hit_rate(out, label, k=10)

    optimizer = dspy.teleprompt.BootstrapFewShotWithRandomSearch(
        metric=metric, max_bootstrapped_demos=6, num_candidate_programs=8
    )
    compiled = optimizer.compile(program, trainset=examples)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compiled.save(str(out_path))
    print("saved", out_path)


def compile_intent(dataset_path: Path, out_path: Path) -> None:
    ensure_dspy_configured()
    rows = read_jsonl(dataset_path)
    examples: List[dspy.Example] = []
    for r in rows:
        # intent 라벨이 있으면(추가 예정) 사용. 현재는 스캐폴딩만.
        if "label_intent" not in r:
            continue
        examples.append(
            dspy.Example(
                user_query=r.get("user_query", ""),
                intent=r["label_intent"],
            ).with_inputs("user_query")
        )
    if len(examples) < 2:
        raise ValueError(
            "Dataset too small. Need at least 2 labeled intent examples to compile."
        )

    program = IntentAnalysisAgent()
    optimizer = dspy.teleprompt.BootstrapFewShotWithRandomSearch(
        max_bootstrapped_demos=6, num_candidate_programs=8
    )
    compiled = optimizer.compile(program, trainset=examples)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compiled.save(str(out_path))
    print("saved", out_path)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--module",
        choices=["relaxed_constraints", "product_ranker", "fusion_decision", "intent"],
        required=True,
    )
    p.add_argument("--dataset", required=True)
    p.add_argument("--out", required=True)
    p.add_argument(
        "--reload-url",
        default=os.getenv("AGENT_RELOAD_URL", ""),
        help="artifact 저장 후 호출할 /admin/reload_artifacts URL (예: http://127.0.0.1:8000/admin/reload_artifacts)",
    )
    p.add_argument(
        "--admin-key",
        default=os.getenv("ADMIN_API_KEY", ""),
        help="서버 ADMIN_API_KEY 설정 시 필요. 헤더 x-admin-key 로 전달.",
    )
    args = p.parse_args()

    # ensure LM is set (Bedrock) via env/.env
    ensure_dspy_configured(model=SETTINGS.dspy_model)

    ds = Path(args.dataset)
    out = Path(args.out)

    if args.module == "relaxed_constraints":
        compile_relaxed_constraints(ds, out)
    elif args.module == "product_ranker":
        compile_product_ranker(ds, out)
    elif args.module == "fusion_decision":
        compile_fusion_decision(ds, out)
    elif args.module == "intent":
        compile_intent(ds, out)

    # optional: notify running server to reload artifacts
    if args.reload_url:
        headers = {}
        if args.admin_key:
            headers["x-admin-key"] = args.admin_key
        try:
            r = httpx.post(args.reload_url, headers=headers, timeout=10.0)
            r.raise_for_status()
            print("reload_ok", r.json())
        except Exception as e:
            print("reload_failed", str(e))


if __name__ == "__main__":
    main()

