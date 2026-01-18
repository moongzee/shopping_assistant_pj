from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from ..core.curation import load_curation_state


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


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def build_datasets(
    chat_log: Path,
    feedback_log: Path,
    out_ranker: Path,
    out_relax: Path,
    out_fusion: Path,
) -> dict:
    chats = read_jsonl(chat_log)
    feedbacks = read_jsonl(feedback_log)
    fb_by_mid = {f.get("message_id"): f for f in feedbacks if f.get("message_id")}

    curation = load_curation_state()
    excluded = set(curation.excluded_message_ids)
    bad_labeled = {mid for mid, v in curation.quality_labels.items() if v == "bad"}
    excluded |= bad_labeled

    ranker_rows: List[Dict[str, Any]] = []
    relax_rows: List[Dict[str, Any]] = []
    fusion_rows: List[Dict[str, Any]] = []

    for c in chats:
        mid = c.get("message_id")
        if not mid:
            continue
        if mid in excluded:
            continue

        fb = fb_by_mid.get(mid)
        selected = (fb or {}).get("selected_style_codes") if isinstance(fb, dict) else None
        if isinstance(selected, list) and selected:
            products = c.get("structured_products", [])
            if not isinstance(products, list):
                products = []

            ranker_rows.append(
                {
                    "user_query": c.get("user_query", ""),
                    "conversation_history": "",
                    "products_json": json.dumps(products, ensure_ascii=False),
                    "label_style_codes": [x for x in selected if isinstance(x, str)],
                    "meta": {"message_id": mid},
                }
            )

            un = c.get("unstructured", {}) if isinstance(c.get("unstructured"), dict) else {}
            fusion_rows.append(
                {
                    "user_query": c.get("user_query", ""),
                    "conversation_history": "",
                    "products_json": json.dumps(products, ensure_ascii=False),
                    "reviews_summary": (un.get("review_summary") or ""),
                    "review_style_codes_json": json.dumps(
                        un.get("review_style_codes", []) or [], ensure_ascii=False
                    ),
                    "label_style_codes": [x for x in selected if isinstance(x, str)],
                    "meta": {"message_id": mid},
                }
            )

        st = c.get("structured") if isinstance(c.get("structured"), dict) else {}
        attempts = st.get("constraints_attempts", []) if isinstance(st, dict) else []
        used = st.get("constraints_used") if isinstance(st, dict) else None
        if isinstance(attempts, list) and used and isinstance(used, str):
            relax_rows.append(
                {
                    "user_query": c.get("user_query", ""),
                    "strict_constraints": attempts[0] if attempts else "",
                    "brand_hint": "",
                    "label_candidates": [used],
                    "meta": {"message_id": mid},
                }
            )

    write_jsonl(out_ranker, ranker_rows)
    write_jsonl(out_relax, relax_rows)
    write_jsonl(out_fusion, fusion_rows)

    return {
        "ranker_examples": len(ranker_rows),
        "relax_examples": len(relax_rows),
        "fusion_examples": len(fusion_rows),
        "excluded_message_ids": len(excluded),
        "out_ranker": str(out_ranker),
        "out_relax": str(out_relax),
        "out_fusion": str(out_fusion),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--chat_log", default="agent/data/logs/chat.jsonl")
    p.add_argument("--feedback_log", default="agent/data/logs/feedback.jsonl")
    p.add_argument(
        "--out_ranker",
        default="agent/data/datasets/ranker.jsonl",
        help="ProductRanker 학습용",
    )
    p.add_argument(
        "--out_relax",
        default="agent/data/datasets/relaxed_constraints.jsonl",
        help="RelaxedConstraintsGenerator 학습용(기본은 로그 기반 약지도)",
    )
    p.add_argument(
        "--out_fusion",
        default="agent/data/datasets/fusion.jsonl",
        help="FusionDecisionMaker 학습용(피드백 기반)",
    )
    args = p.parse_args()

    result = build_datasets(
        chat_log=Path(args.chat_log),
        feedback_log=Path(args.feedback_log),
        out_ranker=Path(args.out_ranker),
        out_relax=Path(args.out_relax),
        out_fusion=Path(args.out_fusion),
    )

    print("wrote", result["ranker_examples"], "ranker examples ->", result["out_ranker"])
    print("wrote", result["relax_examples"], "relax examples ->", result["out_relax"])
    print("wrote", result["fusion_examples"], "fusion examples ->", result["out_fusion"])


if __name__ == "__main__":
    main()

