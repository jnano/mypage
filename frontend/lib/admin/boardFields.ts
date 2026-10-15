// 게시판 설정 칸 명세 — 설정 화면의 입력칸과 Server Action 의 해석이 같은 표를 쓴다(§14.2 '설정 편집').
// 칸 이름은 FastAPI BoardUpdate 와 같다. 점(.)이 든 이름은 JSON 칸 안쪽(display.views 등).

export type FieldType = "text" | "textarea" | "int" | "intOrEmpty" | "bool" | "select" | "multi" | "lines";

export interface FieldSpec {
  name: string;
  label: string;
  type: FieldType;
  options?: [string, string][];
  help?: string;
}

export interface SectionSpec {
  id: string;
  title: string;
  fields: FieldSpec[];
  /** 이 칸 묶음을 통째로 보내는 JSON 칸(display·upload_policy·spam_policy) */
  json?: "display" | "upload_policy" | "spam_policy";
}

const LEVEL_HELP = "0 = 비회원, 1 이상 = 회원 등급";
const level = (name: string, label: string): FieldSpec => ({ name, label, type: "int", help: LEVEL_HELP });

export const BOARD_SECTIONS: SectionSpec[] = [
  {
    id: "basic",
    title: "기본",
    fields: [
      { name: "name", label: "이름", type: "text" },
      { name: "slug", label: "주소(slug)", type: "text", help: "바꾸면 옛 주소는 새 주소로 넘겨 준다" },
      { name: "description", label: "설명", type: "textarea" },
      { name: "kind", label: "형식", type: "select", options: [["default", "일반"], ["gallery", "갤러리"], ["line", "한 줄"]] },
      { name: "group_id", label: "분류 그룹", type: "select", options: [] },
      { name: "is_active", label: "사용", type: "bool" },
      { name: "show_in_menu", label: "메뉴에 보이기", type: "bool" },
    ],
  },
  {
    id: "access",
    title: "권한",
    fields: [
      level("list_level", "목록 보기"),
      level("read_level", "글 읽기"),
      level("write_level", "글쓰기"),
      level("comment_level", "댓글"),
      level("upload_level", "파일 올리기"),
      level("download_level", "첨부 내려받기"),
      { name: "allow_level_lowering", label: "글마다 열람 등급 낮추기 허용", type: "bool" },
    ],
  },
  {
    id: "list",
    title: "목록 표시",
    fields: [
      { name: "posts_per_page", label: "쪽당 글 수(5~100)", type: "int" },
      { name: "hidden_post_listing", label: "볼 수 없는 글", type: "select", options: [["mask", "제목을 가려 보이기"], ["hide", "목록에서 빼기"]] },
      { name: "pinned_display", label: "고정 글", type: "select", options: [["strip", "목록 위 띠"], ["inline", "목록 안"]] },
      { name: "view_count_mode", label: "조회수 세기", type: "select", options: [["daily", "하루 한 번"], ["once", "한 번만"], ["always", "볼 때마다"]] },
    ],
  },
  {
    id: "display",
    title: "보기 방식(스킨)",
    json: "display",
    fields: [
      { name: "display.views", label: "고를 수 있는 보기", type: "multi", options: [["list", "목록"], ["card", "카드"], ["photo", "사진"], ["line", "한 줄"]] },
      { name: "display.default_view", label: "처음 보기", type: "select", options: [["list", "목록"], ["card", "카드"], ["photo", "사진"], ["line", "한 줄"]] },
      {
        name: "display.list_columns",
        label: "목록 칸",
        type: "multi",
        options: [["category", "카테고리"], ["author", "작성자"], ["date", "날짜"], ["views", "조회"], ["likes", "추천"], ["comments", "댓글"]],
      },
      { name: "display.author_display", label: "작성자 표기", type: "select", options: [["name", "이름"], ["hidden", "숨김"]] },
      { name: "display.list_below_post", label: "글 보기 아래 목록", type: "bool" },
    ],
  },
  {
    id: "write",
    title: "글쓰기",
    fields: [
      { name: "editor", label: "새 글 에디터", type: "select", options: [["rich", "리치"], ["markdown", "마크다운"]], help: "이미 쓴 글은 쓴 형식으로 연다" },
      { name: "allow_secret", label: "비밀글 허용", type: "bool" },
      { name: "allow_comments", label: "댓글 허용", type: "bool" },
      { name: "allow_share", label: "공유 허용", type: "bool" },
      { name: "allow_title_style", label: "제목 꾸밈 허용", type: "bool" },
      { name: "protect_commented_posts", label: "댓글 달린 글은 작성자가 지우지 못함", type: "bool" },
      { name: "trash_retention_days", label: "휴지통 보관일(비우면 자동 정리 안 함)", type: "intOrEmpty" },
      { name: "report_auto_blind_threshold", label: "신고 몇 건이면 임시로 가림(비우면 끔)", type: "intOrEmpty" },
    ],
  },
  {
    id: "upload",
    title: "첨부 정책",
    json: "upload_policy",
    fields: [
      { name: "upload_policy.exts", label: "허용 확장자(줄마다 하나)", type: "lines" },
      { name: "upload_policy.max_bytes", label: "파일 하나 최대 바이트", type: "int" },
      { name: "upload_policy.max_files", label: "글당 최대 파일 수", type: "int" },
      { name: "upload_policy.image_max_px", label: "사진 최대 화소 수", type: "int" },
    ],
  },
  {
    id: "spam",
    title: "스팸 정책(비운 칸은 사이트 기본)",
    json: "spam_policy",
    fields: [
      { name: "spam_policy.banned_words", label: "금지어(줄마다 하나)", type: "lines" },
      { name: "spam_policy.max_links", label: "링크 상한", type: "intOrEmpty" },
      { name: "spam_policy.interval_sec", label: "작성 간격(초)", type: "intOrEmpty" },
      { name: "spam_policy.min_len", label: "최소 글자 수", type: "intOrEmpty" },
      { name: "spam_policy.max_len", label: "최대 글자 수", type: "intOrEmpty" },
      { name: "spam_policy.min_elapsed_sec", label: "비회원 폼 최소 경과(초)", type: "intOrEmpty" },
    ],
  },
  {
    id: "seo",
    title: "검색·SEO",
    fields: [
      { name: "indexable", label: "검색엔진 색인 허용(끄면 sitemap·RSS 제외)", type: "bool" },
      { name: "exclude_from_search", label: "사이트 통합 검색에서 빼기", type: "bool" },
    ],
  },
];

type Json = Record<string, unknown>;

function get(source: Json, path: string): unknown {
  return path.split(".").reduce<unknown>((v, k) => (v && typeof v === "object" ? (v as Json)[k] : undefined), source);
}

/** 화면에 채울 값(문자열·불·목록) */
export function fieldValue(board: Json, field: FieldSpec): string | boolean | string[] {
  const v = get(board, field.name);
  if (field.type === "bool") return v === true;
  if (field.type === "multi") return Array.isArray(v) ? v.map(String) : [];
  if (field.type === "lines") return Array.isArray(v) ? v.join("\n") : "";
  return v === null || v === undefined ? "" : String(v);
}

/** 폼 → PATCH 본문. 한 구역의 칸만 보낸다. 해석할 수 없는 숫자는 문자열 그대로 보내 서버가 422 로 알려 준다 */
export function parseSection(section: SectionSpec, form: FormData): Json {
  const body: Json = {};
  const nested: Json = {};
  for (const field of section.fields) {
    const raw = form.get(field.name);
    let value: unknown;
    switch (field.type) {
      case "bool":
        value = raw === "on";
        break;
      case "multi":
        value = form.getAll(field.name).map(String);
        break;
      case "lines":
        value = String(raw ?? "")
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean);
        if (section.json === "spam_policy" && (value as string[]).length === 0) value = undefined;
        break;
      case "int":
      case "intOrEmpty": {
        const text = String(raw ?? "").trim();
        if (text === "") value = field.type === "intOrEmpty" ? null : "";
        else value = /^-?\d+$/.test(text) ? Number(text) : text;
        // 스팸 덮어쓰기에서 빈 칸은 '사이트 기본을 따름' — 칸을 보내지 않는다
        if (section.json === "spam_policy" && value === null) value = undefined;
        break;
      }
      default:
        value = String(raw ?? "");
        if (field.name === "group_id") value = value === "" ? null : Number(value);
        if (field.name === "description" && value === "") value = null;
    }
    if (value === undefined) continue;
    if (section.json) nested[field.name.split(".")[1]] = value;
    else body[field.name] = value;
  }
  if (section.json) body[section.json] = section.json === "spam_policy" && Object.keys(nested).length === 0 ? null : nested;
  return body;
}
