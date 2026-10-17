"""홈블록 상한 — 홈블록 설계도 §3.5·§4.3. 근거는 §12 의 쿼리 수·응답 크기 예산과 주소 집합 캐시 크기."""

MAX_BLOCKS_PER_OWNER = 60  # 틀 하나·페이지 하나의 블록 수
MAX_DYNAMIC_BLOCKS = 10  # 그중 데이터를 부르는 블록(types.DYNAMIC_BLOCK_TYPES)
MAX_DEPTH = 2  # group·columns 아래 한 단
MAX_MODULES_PER_PAGE = 1  # 화면당 호출 예산(§5.2)
MAX_PAGES = 1_000  # 주소 집합(GET /api/pages/paths)을 통째로 캐시한다(§5.5)
PATH_HISTORY_PER_PAGE = 10  # 옛 주소 기록
MAX_MENU_DEPTH = 3  # 메뉴 항목 트리(§4.5)
MAX_MENU_ITEMS = 200  # 메뉴 하나의 항목 수(§11 '상한 60·200', §12 최대 구성)
