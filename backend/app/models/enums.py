"""열거형 값 — DB CHECK 와 Pydantic 검증이 같은 값을 쓴다(설계도 §4)."""

MEMBER_STATUSES = ("pending", "active", "withdrawn")
LEVEL_REQUEST_STATUSES = ("pending", "approved", "rejected", "cancelled")

BOARD_KINDS = ("default", "gallery", "line")
HIDDEN_POST_LISTINGS = ("mask", "hide")
PINNED_DISPLAYS = ("strip", "inline")
VIEW_COUNT_MODES = ("always", "daily", "once")
EDITORS = ("rich", "markdown")
ACCESS_SUBJECT_TYPES = ("member", "group")

POST_STATUSES = ("draft", "scheduled", "pending", "published", "trashed")
POST_RESTORABLE_STATUSES = ("draft", "scheduled", "pending", "published")
CONTENT_FORMATS = EDITORS
BLIND_SOURCES = ("manual", "auto_report")
POSTED_AS = ("personal", "admin")
REACTION_KINDS = ("like",)

COMMENT_STATUSES = ("published", "deleted")

ATTACHMENT_ROLES = ("attachment", "inline")
ATTACHMENT_VISIBILITIES = ("public", "private")

REPORT_TARGET_TYPES = ("post", "comment")
REPORT_STATUSES = ("open", "resolved_blinded", "resolved_trashed", "resolved_deleted", "dismissed")
# 신고 사유(reason_code 는 DB CHECK 없이 앱이 검증 — 사유 목록은 운영하며 늘린다)
REPORT_REASONS = ("spam", "abuse", "privacy", "copyright", "illegal", "other")
MODERATION_TARGET_TYPES = ("board", "post", "comment", "report", "member", "sanction", "setting", "group")
SANCTION_ACTIONS = ("write", "comment", "upload")
