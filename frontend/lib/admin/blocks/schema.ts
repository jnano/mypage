// 블록 설정 폼의 형식 읽기(홈블록 설계도 §8) — GET /api/admin/block-types 가 주는 JSON Schema(Pydantic 이 만든 것 +
// 칸 이름·x-widget·x-enum-labels)만 보고 폼을 만든다. 칸 명세를 프런트에 따로 쓰지 않는다(원칙 2).
// 여기는 순수 함수만 — 부품은 components/admin/blocks/ConfigForm.tsx

export type JsonSchema = {
  type?: string;
  title?: string;
  default?: unknown;
  enum?: (string | number)[];
  const?: string | number;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  minItems?: number;
  maxItems?: number;
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  discriminator?: { propertyName: string; mapping: Record<string, string> };
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  additionalProperties?: boolean;
  "x-widget"?: string;
  "x-enum-labels"?: Record<string, string>;
};

export type FieldKind =
  | "boolean"
  | "text"
  | "textarea"
  | "markdown"
  | "number"
  | "select"
  | "image"
  | "menu"
  | "page"
  | "board"
  | "boards"
  | "module"
  | "module-params"
  | "list"
  | "object"
  | "union";

const WIDGETS = new Set<FieldKind>(["textarea", "markdown", "image", "menu", "page", "board", "boards", "module", "module-params"]);

/** "#/$defs/Name" 을 따라간다(Pydantic 은 $defs 한 층만 쓴다) */
export function deref(s: JsonSchema, root: JsonSchema): JsonSchema {
  if (!s.$ref) return s;
  const name = s.$ref.replace(/^#\/\$defs\//, "");
  const target = root.$defs?.[name];
  if (!target) throw new Error(`형식에 없는 참조: ${s.$ref}`);
  return { ...target, title: s.title ?? target.title };
}

/** `X | None` → (X, 빈 값 허용). 이름·부품·기본값은 바깥 칸의 것을 X 에 얹는다 */
export function unwrapNullable(s: JsonSchema): { schema: JsonSchema; nullable: boolean } {
  const options = s.anyOf;
  if (!options || !options.some((o) => o.type === "null")) return { schema: s, nullable: false };
  const rest = options.filter((o) => o.type !== "null");
  const inner: JsonSchema = rest.length === 1 ? rest[0] : { anyOf: rest };
  return {
    schema: { ...inner, title: s.title, "x-widget": s["x-widget"] ?? inner["x-widget"], "x-enum-labels": s["x-enum-labels"] ?? inner["x-enum-labels"] },
    nullable: true,
  };
}

export function fieldKind(raw: JsonSchema, root: JsonSchema): FieldKind {
  const s = deref(raw, root);
  const widget = s["x-widget"] as FieldKind | undefined;
  if (widget && WIDGETS.has(widget)) return widget;
  if (s.oneOf) return "union";
  if (s.enum) return "select";
  switch (s.type) {
    case "boolean":
      return "boolean";
    case "integer":
    case "number":
      return "number";
    case "array":
      return "list";
    case "object":
      return "object";
    default:
      return "text";
  }
}

export interface Variant {
  key: string;
  label: string;
  schema: JsonSchema;
}

/** 꼬리표로 가르는 합(링크: page·board·url) — 꼬리표 값·보이는 이름·그 갈래의 형식 */
export function variants(s: JsonSchema, root: JsonSchema): Variant[] {
  const tag = s.discriminator?.propertyName;
  if (!tag || !s.oneOf) return [];
  return s.oneOf.map((ref) => {
    const v = deref(ref, root);
    const prop = v.properties?.[tag];
    const key = String(prop?.const ?? "");
    return { key, label: prop?.["x-enum-labels"]?.[key] ?? key, schema: v };
  });
}

export function enumLabel(s: JsonSchema, value: string | number | null): string {
  if (value === null) return "정하지 않음";
  return s["x-enum-labels"]?.[String(value)] ?? String(value);
}

/** 새 블록·새 항목의 첫 값 — 형식의 기본값, 없으면 빈 값(필수 칸은 비워 둬서 저장·미리보기 검증이 알리게) */
export function initialValue(raw: JsonSchema, root: JsonSchema): unknown {
  if (raw.default !== undefined) return structuredClone(raw.default);
  const { schema: unwrapped, nullable } = unwrapNullable(raw);
  if (nullable) return null;
  const s = deref(unwrapped, root);
  if (s.const !== undefined) return s.const;
  switch (fieldKind(s, root)) {
    case "boolean":
      return false;
    case "select":
      return s.enum?.[0] ?? null;
    case "boards":
      return []; // 고르기 전 — 최소 개수는 백엔드 검증이 알린다(빈 자리 [null] 을 만들지 않는다, 코드 검토 v16 N-1)
    case "list":
      return Array.from({ length: s.minItems ?? 0 }, () => initialValue(s.items ?? {}, root)).filter((v) => v !== undefined);
    case "union": {
      const [first] = variants(s, root);
      return first ? initialValue(first.schema, root) : null;
    }
    case "object":
      return initialObject(s, root);
    case "module-params":
      return {};
    case "text":
    case "textarea":
    case "markdown":
    case "module":
      return "";
    default:
      return undefined; // 숫자·고르기(id) — 비워 둔다
  }
}

export function initialObject(s: JsonSchema, root: JsonSchema): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, prop] of Object.entries(s.properties ?? {})) {
    const v = initialValue(prop, root);
    if (v !== undefined) out[name] = v;
  }
  return out;
}

/** 오류 칸 경로 — 백엔드 tree._loc 과 같은 꼴(`blocks[2].config.items[1].url`). 꼬리표 합은 갈래 이름이 한 단 더 붙는다 */
export function join(base: string, key: string | number): string {
  return typeof key === "number" ? `${base}[${key}]` : base ? `${base}.${key}` : key;
}

export interface FieldError {
  field: string;
  message: string;
}

/** 이 칸에 딱 맞는 오류만 */
export function errorsAt(errors: readonly FieldError[], path: string): FieldError[] {
  return errors.filter((e) => e.field === path);
}

/** 화면의 어떤 칸에도 붙지 않은 오류(형식 전체의 규칙·모르는 칸) — 폼 위에 모아 보인다 */
export function unplaced(errors: readonly FieldError[], placed: ReadonlySet<string>): FieldError[] {
  return errors.filter((e) => !placed.has(e.field));
}

/** GET /api/admin/block-types 응답 */
export interface BlockTypeInfo {
  type: string;
  label: string;
  group: "site" | "content" | "dynamic" | "structure" | "empty";
  places: ("layout" | "page")[];
  available: boolean;
  schema?: JsonSchema;
  example?: Record<string, unknown>;
  help?: string;
}

export interface BlockTypes {
  types: BlockTypeInfo[];
  modules: Record<string, { label: string; available: boolean; schema: JsonSchema }>;
  menu_item: JsonSchema; // 메뉴 항목 폼(라벨·링크·최소 등급·보이기)
  regions: string[];
  audiences: string[];
}
