"""알림 종류와 기본 수신 설정 — 설계도 §7 표. 수신 설정 행(notification_prefs)은 기본값을 바꿀 때만 생긴다."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationType:
    name: str
    label: str
    default_enabled: bool


TYPES: dict[str, NotificationType] = {
    t.name: t
    for t in [
        NotificationType("comment.on_my_post", "내 글에 댓글", True),
        NotificationType("comment.reply", "내 댓글에 답글", True),
        NotificationType("board.new_post", "구독한 게시판의 새 글", True),  # 구독했을 때만 받는다
        NotificationType("moderation.blinded", "내 글·댓글이 가려짐", True),
        NotificationType("moderation.moved", "내 글이 다른 게시판으로 옮겨짐", False),
        NotificationType("admin.guest_pending", "승인 대기 글(담당자)", True),
        NotificationType("admin.report", "신고 접수(담당자)", True),
        NotificationType("report.resolved", "내 신고가 처리됨", False),
    ]
}
