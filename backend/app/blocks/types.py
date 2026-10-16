"""블록 종류의 원본 — 홈블록 설계도 §2.2·§4.3.

DB CHECK(`blocks.type`)·관리 화면·생성 파일이 이 목록을 쓴다. 개수·순서를 시험에 하드코딩하지 않는다(D-706).
"""

# 지금 쓸 수 있는 종류(§2.2 표 순서). outlet 은 렌더러가 놓는 자리라 행이 없다(§3.1)
BLOCK_TYPES: tuple[str, ...] = (
    # 사이트
    "site_brand",
    "menu",
    "sub_menu",
    "breadcrumb",
    "search_box",
    "account",
    "footer_info",
    # 콘텐츠
    "heading",
    "text",
    "image",
    "banner",
    "buttons",
    "link_list",
    "video",
    "details",
    "divider",
    # 동적
    "recent_posts",
    "recent_comments",
    "board_links",
    # 구조
    "group",
    "columns",
    # 빈 블록
    "outlet",
    "module",
)

# 2단계 대기(§2.2 — 종류 표에 available: false 로만). 행을 만들 수 없다 — 쓸 수 있게 될 때 BLOCK_TYPES 로 옮기고 CHECK 를 바꾼다
PENDING_BLOCK_TYPES: tuple[str, ...] = ("popular_posts", "visitor_count", "popup", "map", "calendar")

# 행이 될 수 있는 종류 = DB CHECK 의 목록
STORED_BLOCK_TYPES: tuple[str, ...] = tuple(t for t in BLOCK_TYPES if t != "outlet")

# 틀의 영역(§3.1) — 스킨 계약(data-region). 운영자가 늘리지 않는다
REGIONS: tuple[str, ...] = ("header", "nav", "top", "aside", "bottom", "footer")

AUDIENCES: tuple[str, ...] = ("all", "guest", "member")

# 메뉴 항목의 링크 종류(§4.5). none = 링크 없는 묶음 제목
MENU_LINK_KINDS: tuple[str, ...] = ("page", "board", "url", "none")
