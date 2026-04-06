"""
실패 처리 Facade — 재호출 루프 조율.

1단계: 정상 배치
2단계: Agent 3 재호출 (최대 MAX_RETRIES회) — classifier가 분류 + 피드백 생성
3단계: Deterministic Fallback — fallback_placement가 강제 배치
"""
from app.schemas.placement import Placement
from app.modules.placement_engine import run_placement_loop
from app.modules.failure_classifier import classify_failures, generate_choke_feedback
from app.modules.fallback_placement import deterministic_fallback
from app.core.exceptions import (
    AllSlotsExhaustedError,
    LLMParsingError,
    LLMValidationError,
)

MAX_RETRIES = 3
_RETRYABLE_EXCEPTIONS = (AllSlotsExhaustedError, LLMValidationError, LLMParsingError)


def run_with_fallback(
    placements: list[Placement],
    eligible_objects: list[dict],
    space_data: dict,
    brand_data: dict,
    plan_fn=None,
) -> dict:
    """배치 엔진 + 실패 처리 통합 진입점 (Facade)."""
    all_log: list[str] = []
    retry_count = 0
    current_placements = placements
    feedback = ""
    result = None
    placed_with_poly = []

    for attempt in range(1 + MAX_RETRIES):
        is_retry = attempt > 0

        if is_retry:
            if not plan_fn:
                print(f"[FailureHandler] plan_fn 없음 — fallback 진입")
                break

            retry_count += 1
            print(f"[FailureHandler] === Agent 3 재호출 #{retry_count} ===")

            try:
                current_placements = plan_fn(
                    eligible_objects, space_data, brand_data, feedback
                )
            except _RETRYABLE_EXCEPTIONS as e:
                print(f"[FailureHandler] Agent 3 재호출 실패: {type(e).__name__}: {e}")
                feedback = f"Agent 3 재호출 실패: {e}"
                all_log.append(f"retry #{retry_count}: Agent 3 실패 — {e}")
                continue

        result = run_placement_loop(
            current_placements, eligible_objects, space_data, brand_data,
            existing_placed=None,
        )
        placed_with_poly = list(result.get("_placed_raw", result["placed"]))
        all_log.extend(result["log"])

        if not result["failed"]:
            print(f"[FailureHandler] all placed on attempt {attempt + 1}")
            return {
                "placed": result["placed"],
                "dropped": [],
                "log": all_log,
                "fallback_used": is_retry,
                "reset_count": retry_count,
            }

        cascade, physical = classify_failures(
            result["failed"], eligible_objects, space_data, brand_data,
            original_placements=current_placements,
        )

        feedback = generate_choke_feedback(cascade, result["placed"], space_data)
        all_log.append(
            f"attempt {attempt + 1}: {len(result['placed'])} placed, "
            f"{len(cascade)} cascade, {len(physical)} physical"
        )

        if not cascade:
            print(f"[FailureHandler] no cascade — fallback 진입")
            break

    if retry_count >= MAX_RETRIES and result and result["failed"]:
        print(f"[FailureHandler] Circuit Breaker: {MAX_RETRIES}회 소진")
        all_log.append(f"Circuit Breaker: {MAX_RETRIES}회 소진")

    dropped = []
    if result and result["failed"]:
        print(f"[FailureHandler] deterministic fallback: {len(result['failed'])} objects")
        fallback_result = deterministic_fallback(
            result["failed"], eligible_objects, space_data, placed_with_poly
        )
        result["placed"].extend(fallback_result["placed"])
        dropped = fallback_result["dropped"]
        all_log.extend(fallback_result["log"])

    placed = result["placed"] if result else []
    print(f"[FailureHandler] final: {len(placed)} placed, {len(dropped)} dropped, {retry_count} retries")

    return {
        "placed": placed,
        "dropped": dropped,
        "log": all_log,
        "fallback_used": True,
        "reset_count": retry_count,
    }
