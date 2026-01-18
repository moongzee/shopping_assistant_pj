from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..dspy_modules.recommender import FusionDecisionMaker, ProductRanker, RelaxedConstraintsGenerator
from ..dspy_modules.intent import ensure_dspy_configured
from .config import SETTINGS


def _artifact_path(filename: str) -> Path:
    base = Path(SETTINGS.dspy_artifacts_dir)
    if not base.is_absolute():
        base = (Path.cwd() / base).resolve()
    return (base / filename).resolve()


_RELAXED: Optional[RelaxedConstraintsGenerator] = None
_RANKER: Optional[ProductRanker] = None
_FUSION: Optional[FusionDecisionMaker] = None


def reset_caches() -> None:
    global _RELAXED, _RANKER, _FUSION
    _RELAXED = None
    _RANKER = None
    _FUSION = None


def _load_if_exists(prog, filename: str) -> None:
    path = _artifact_path(filename)
    if path.exists():
        try:
            prog.load(str(path))
        except Exception:
            pass


def get_relaxed_constraints_generator() -> RelaxedConstraintsGenerator:
    global _RELAXED
    if _RELAXED is not None:
        return _RELAXED
    ensure_dspy_configured()
    prog = RelaxedConstraintsGenerator()
    _load_if_exists(prog, SETTINGS.artifact_relaxed_constraints)
    _RELAXED = prog
    return prog


def get_product_ranker() -> ProductRanker:
    global _RANKER
    if _RANKER is not None:
        return _RANKER
    ensure_dspy_configured()
    prog = ProductRanker()
    _load_if_exists(prog, SETTINGS.artifact_product_ranker)
    _RANKER = prog
    return prog


def get_fusion_decision_maker() -> FusionDecisionMaker:
    global _FUSION
    if _FUSION is not None:
        return _FUSION
    ensure_dspy_configured()
    prog = FusionDecisionMaker()
    _load_if_exists(prog, SETTINGS.artifact_fusion_decision)
    _FUSION = prog
    return prog


def reload_all() -> dict:
    reset_caches()
    # Instantiate once to force load now
    _ = get_relaxed_constraints_generator()
    _ = get_product_ranker()
    _ = get_fusion_decision_maker()
    return {
        "artifacts_dir": str(_artifact_path(".")),
        "files": {
            "relaxed_constraints": str(_artifact_path(SETTINGS.artifact_relaxed_constraints)),
            "product_ranker": str(_artifact_path(SETTINGS.artifact_product_ranker)),
            "fusion_decision": str(_artifact_path(SETTINGS.artifact_fusion_decision)),
        },
    }

