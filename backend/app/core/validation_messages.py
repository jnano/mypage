"""검증 오류 문구 — 홈블록 설계도 M-9(2026-10-17 사용자 결정: 전역 한 곳). 요청 본문 검증(FastAPI RequestValidationError, problems.py)과
블록 설정 검증(blocks.tree)이 같은 함수를 쓴다. 바뀌는 것은 문구(message)뿐 — 칸 경로·코드·상태는 그대로.
"""

from typing import Any


def ko_message(err: Any) -> str:
    """Pydantic 오류 하나(e.errors() 의 dict) → 화면에 보일 한국어 문구. 우리 검증기의 문구(ValueError)는 'Value error, ' 머리만 뗀다.
    모르는 종류는 원문 그대로(빠진 번역이 오류를 숨기지 않게)"""
    ctx = err.get("ctx") or {}
    match err["type"]:
        case "value_error":
            return str(ctx.get("error", err["msg"]))
        case "missing":
            return "필요한 칸입니다"
        case "string_too_short":
            return "비어 있습니다" if ctx.get("min_length") == 1 else f"{ctx.get('min_length')}자 이상이어야 합니다"
        case "string_too_long":
            return f"{ctx.get('max_length')}자까지입니다"
        case "too_short":
            return f"{ctx.get('min_length')}개 이상 골라야 합니다" if ctx.get("min_length") else "비어 있습니다"
        case "too_long":
            return f"{ctx.get('max_length')}개까지입니다"
        case "greater_than_equal":
            return f"{ctx.get('ge')} 이상이어야 합니다"
        case "less_than_equal":
            return f"{ctx.get('le')} 이하여야 합니다"
        case "int_parsing" | "int_type" | "int_from_float":
            return "숫자를 넣습니다"
        case "string_type":
            return "글자를 넣습니다"
        case "bool_type" | "bool_parsing":
            return "참·거짓 값이어야 합니다"
        case "literal_error" | "enum":
            return "고를 수 있는 값이 아닙니다"
        case "union_tag_invalid" | "union_tag_not_found":
            return "링크 종류를 고릅니다"
        case "extra_forbidden":
            return "모르는 칸입니다"
        case "string_pattern_mismatch":
            return "형식이 맞지 않습니다"
        case "float_parsing" | "float_type" | "decimal_parsing":
            return "숫자를 넣습니다"
        case "date_parsing" | "date_from_datetime_parsing" | "date_type":
            return "날짜 형식이 맞지 않습니다"
        case "datetime_parsing" | "datetime_from_date_parsing" | "datetime_type":
            return "날짜·시각 형식이 맞지 않습니다"
        case "list_type":
            return "목록이어야 합니다"
        case "dict_type" | "model_type" | "model_attributes_type":
            return "형식이 맞지 않습니다"
        case "json_invalid":
            return "본문이 올바른 JSON 이 아닙니다"
        case "greater_than":
            return f"{ctx.get('gt')}보다 커야 합니다"
        case "less_than":
            return f"{ctx.get('lt')}보다 작아야 합니다"
    return err["msg"]
