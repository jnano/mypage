"""사이트 날짜 — 사이트 시간대(설계도 §3.7)의 오늘. DB 세션 시간대의 current_date 를 쓰지 않는다.

날짜별 기록(조회수 daily §6.1, 검색어 집계 §9.1)과 그 정리 작업이 같은 규칙을 쓴다.
"""

from sqlalchemy import func

from app.core.config import settings


def site_today():
    return func.date(func.timezone(settings.site_time_zone, func.now()))
