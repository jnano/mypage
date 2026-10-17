"use client";

import { useId, useState, type ReactNode } from "react";
import {
  deref,
  enumLabel,
  errorsAt,
  fieldKind,
  initialObject,
  initialValue,
  join,
  unwrapNullable,
  variants,
  type BlockTypes,
  type FieldError,
  type JsonSchema,
} from "@/lib/admin/blocks/schema";

// 블록 설정 폼(홈블록 설계도 §8) — GET /api/admin/block-types 의 형식만 보고 칸을 만든다. 값은 부르는 쪽(편집기)이 가진다.
// 오류는 저장·미리보기 응답의 errors[].field(`blocks[2].config.items[1].url`)를 칸 경로와 맞춰 칸 옆에 보인다.
// 접근성: 칸마다 <label>, 묶음은 <fieldset><legend>, 오류는 aria-invalid + aria-describedby(§10·본 §13)

export interface ConfigOptions {
  boards: { id: number; name: string }[];
  pages: { id: number; path: string; title: string }[];
  menus: { id: number; name: string }[];
  modules: BlockTypes["modules"];
  /** 사이트 업로드(target=site) — 올린 그림의 첨부 id */
  upload: (file: File) => Promise<{ ok: true; id: number } | { ok: false; message: string }>;
}

interface FieldProps {
  schema: JsonSchema;
  root: JsonSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  path: string;
  errors: readonly FieldError[];
  options: ConfigOptions;
  required: boolean;
}

export function ConfigForm({
  schema,
  value,
  onChange,
  path,
  errors,
  options,
}: {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  path: string;
  errors: readonly FieldError[];
  options: ConfigOptions;
}) {
  return (
    <div data-slot="config-form">
      <ErrorText errors={errorsAt(errors, path)} />
      <Properties schema={schema} root={schema} value={value} onChange={onChange} path={path} errors={errors} options={options} />
    </div>
  );
}

function Properties({
  schema,
  root,
  value,
  onChange,
  path,
  errors,
  options,
  skip,
}: Omit<FieldProps, "value" | "onChange" | "required"> & {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  skip?: string;
}) {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {})
    .filter(([name]) => name !== skip)
    .map(([name, prop]) => (
      <Field
        key={name}
        schema={prop}
        root={root}
        value={value[name]}
        onChange={(v) => {
          const next = { ...value };
          if (v === undefined) delete next[name];
          else next[name] = v;
          onChange(next);
        }}
        path={join(path, name)}
        errors={errors}
        options={options}
        required={required.has(name)}
      />
    ));
}

function ErrorText({ errors, id }: { errors: readonly FieldError[]; id?: string }) {
  if (errors.length === 0) return null;
  return (
    <p id={id} data-slot="field-error">
      {errors.map((e) => e.message).join(" · ")}
    </p>
  );
}

function Field(props: FieldProps) {
  const { schema: raw, root, value, onChange, path, errors, options, required } = props;
  const id = useId();
  const errId = `${id}-err`;
  const own = errorsAt(errors, path);
  const { schema: unwrapped, nullable } = unwrapNullable(raw);
  const s = deref(unwrapped, root);
  const title = raw.title ?? s.title ?? path;
  const kind = fieldKind(s, root);
  const a11y = { id, "aria-invalid": own.length > 0 || undefined, "aria-describedby": own.length > 0 ? errId : undefined, required: required && !nullable };
  const err = <ErrorText errors={own} id={errId} />;
  const label = (
    <label htmlFor={id}>
      {title}
      {a11y.required && <span aria-hidden="true"> *</span>}
    </label>
  );

  switch (kind) {
    case "boolean":
      return (
        <div data-slot="field" data-kind="boolean">
          <input type="checkbox" {...a11y} required={false} checked={value === true} onChange={(e) => onChange(e.target.checked)} />
          {label}
          {err}
        </div>
      );
    case "text":
      return (
        <div data-slot="field" data-kind="text">
          {label}
          <input
            type="text"
            {...a11y}
            maxLength={s.maxLength}
            value={typeof value === "string" ? value : ""}
            onChange={(e) => onChange(nullable && e.target.value === "" ? null : e.target.value)}
          />
          {err}
        </div>
      );
    case "textarea":
    case "markdown":
      return (
        <div data-slot="field" data-kind={kind}>
          {label}
          <textarea
            {...a11y}
            rows={kind === "markdown" ? 8 : 3}
            maxLength={s.maxLength}
            value={typeof value === "string" ? value : ""}
            onChange={(e) => onChange(nullable && e.target.value === "" ? null : e.target.value)}
          />
          {kind === "markdown" && <p data-slot="field-help">마크다운으로 씁니다. 그림은 이 블록에 올린 것만 쓸 수 있습니다.</p>}
          {err}
        </div>
      );
    case "number":
      return (
        <div data-slot="field" data-kind="number">
          {label}
          <input
            type="number"
            inputMode="numeric"
            {...a11y}
            min={s.minimum}
            max={s.maximum}
            value={typeof value === "number" ? value : ""}
            onChange={(e) => onChange(e.target.value === "" ? (nullable ? null : undefined) : Number(e.target.value))}
          />
          {err}
        </div>
      );
    case "select":
      return (
        <div data-slot="field" data-kind="select">
          {label}
          <select
            {...a11y}
            value={value === null || value === undefined ? "" : String(value)}
            onChange={(e) => {
              const picked = s.enum?.find((v) => String(v) === e.target.value);
              onChange(picked ?? null);
            }}
          >
            {nullable && <option value="">{enumLabel(s, null)}</option>}
            {s.enum?.map((v) => (
              <option key={String(v)} value={String(v)}>
                {enumLabel(s, v)}
              </option>
            ))}
          </select>
          {err}
        </div>
      );
    case "menu":
    case "page":
    case "board":
    case "module": {
      const choices: [string, string][] =
        kind === "menu"
          ? options.menus.map((m) => [String(m.id), m.name])
          : kind === "page"
            ? options.pages.map((p) => [String(p.id), `${p.title} (${p.path})`])
            : kind === "board"
              ? options.boards.map((b) => [String(b.id), b.name])
              : Object.entries(options.modules)
                  .filter(([, m]) => m.available)
                  .map(([k, m]) => [k, m.label]);
      const current = value === null || value === undefined ? "" : String(value);
      const missing = current !== "" && !choices.some(([k]) => k === current); // 지워진 대상(끊긴 참조)
      return (
        <div data-slot="field" data-kind={kind}>
          {label}
          <select
            {...a11y}
            value={current}
            onChange={(e) => onChange(e.target.value === "" ? (nullable ? null : undefined) : kind === "module" ? e.target.value : Number(e.target.value))}
          >
            <option value="">{nullable ? "없음" : "고르세요"}</option>
            {missing && <option value={current}>(지워진 대상 #{current})</option>}
            {choices.map(([k, name]) => (
              <option key={k} value={k}>
                {name}
              </option>
            ))}
          </select>
          {err}
        </div>
      );
    }
    case "boards":
      return <BoardsField {...props} title={title} errId={errId} own={own} />;
    case "image":
      return <ImageField {...props} title={title} nullable={nullable} errId={errId} own={own} />;
    case "module-params": {
      // 모듈 설정 — 형식은 고른 모듈의 것(같은 config 의 module 칸). 부르는 쪽이 value 와 함께 모듈 키를 모른다:
      // ConfigForm 은 module 칸 다음에 params 를 그리므로 부모 값에서 찾는 대신 등록된 모듈이 하나면 그것을, 아니면 빈 폼
      return <ModuleParams {...props} title={title} />;
    }
    case "list":
      return <ListField {...props} schema={s} title={title} />;
    case "object":
      return (
        <fieldset data-slot="field" data-kind="object">
          <legend>{title}</legend>
          {err}
          <Properties schema={s} root={root} value={(value as Record<string, unknown>) ?? {}} onChange={onChange} path={path} errors={errors} options={options} />
        </fieldset>
      );
    case "union":
      return <UnionField {...props} schema={s} title={title} nullable={nullable} errId={errId} own={own} />;
  }
}

function BoardsField({ value, onChange, options, title, errId, own }: FieldProps & { title: string; errId: string; own: FieldError[] }) {
  const picked = Array.isArray(value) ? (value as number[]) : [];
  const id = useId();
  return (
    <fieldset data-slot="field" data-kind="boards" aria-invalid={own.length > 0 || undefined} aria-describedby={own.length > 0 ? errId : undefined}>
      <legend>{title}</legend>
      {options.boards.map((b) => (
        <div key={b.id}>
          <input
            type="checkbox"
            id={`${id}-${b.id}`}
            checked={picked.includes(b.id)}
            onChange={(e) => onChange(e.target.checked ? [...picked, b.id] : picked.filter((x) => x !== b.id))}
          />
          <label htmlFor={`${id}-${b.id}`}>{b.name}</label>
        </div>
      ))}
      {picked.filter((x) => !options.boards.some((b) => b.id === x)).map((x) => (
        <p key={x}>
          지워진 게시판 #{x}{" "}
          <button type="button" onClick={() => onChange(picked.filter((y) => y !== x))}>
            빼기
          </button>
        </p>
      ))}
      <ErrorText errors={own} id={errId} />
    </fieldset>
  );
}

function ImageField({ value, onChange, options, title, nullable, errId, own }: FieldProps & { title: string; nullable: boolean; errId: string; own: FieldError[] }) {
  const id = useId();
  const [status, setStatus] = useState("");
  const current = typeof value === "number" ? value : null;
  return (
    <fieldset data-slot="field" data-kind="image" aria-invalid={own.length > 0 || undefined} aria-describedby={own.length > 0 ? errId : undefined}>
      <legend>{title}</legend>
      <p>{current ? `올린 그림 #${current}` : "아직 그림이 없습니다."}</p>
      <label htmlFor={id}>{current ? "다른 그림 올리기" : "그림 올리기"}</label>
      <input
        id={id}
        type="file"
        accept="image/*"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          setStatus("올리는 중…");
          const res = await options.upload(file);
          if (res.ok) {
            onChange(res.id);
            setStatus("올렸습니다. 저장해야 블록에 붙습니다.");
          } else setStatus(res.message);
          e.target.value = "";
        }}
      />
      {nullable && current !== null && (
        <button type="button" onClick={() => onChange(null)}>
          그림 빼기
        </button>
      )}
      <p aria-live="polite" data-slot="form-status">
        {status}
      </p>
      <ErrorText errors={own} id={errId} />
    </fieldset>
  );
}

function ModuleParams({ value, onChange, path, errors, options, title }: FieldProps & { title: string }) {
  const keys = Object.keys(options.modules);
  const moduleKey = keys.length === 1 ? keys[0] : null;
  const spec = moduleKey ? options.modules[moduleKey] : null;
  if (!spec) return null;
  return (
    <fieldset data-slot="field" data-kind="module-params">
      <legend>{title}</legend>
      <Properties
        schema={spec.schema}
        root={spec.schema}
        value={(value as Record<string, unknown>) ?? initialObject(spec.schema, spec.schema)}
        onChange={onChange}
        path={path}
        errors={errors}
        options={options}
      />
    </fieldset>
  );
}

function ListField({ schema, root, value, onChange, path, errors, options, title }: FieldProps & { title: string }) {
  const items = Array.isArray(value) ? (value as unknown[]) : [];
  const item = schema.items ?? {};
  const max = schema.maxItems ?? Infinity;
  const min = schema.minItems ?? 0;
  const set = (next: unknown[]) => onChange(next);
  const move = (i: number, d: number) => {
    const next = [...items];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    set(next);
  };
  return (
    <fieldset data-slot="field" data-kind="list">
      <legend>{title}</legend>
      <ErrorText errors={errorsAt(errors, path)} />
      <ol>
        {items.map((v, i) => (
          <li key={i}>
            {/* 항목 이름은 '단추 1' 꼴 — 참조한 모델의 title 은 Pydantic 영문 이름(Button 등)이라 쓰지 않는다(코드 검토 v15 N-4) */}
            <Field schema={{ ...item, title: `${title} ${i + 1}` }} root={root} value={v} onChange={(x) => set(items.map((y, j) => (j === i ? x : y)))} path={join(path, i)} errors={errors} options={options} required />
            <ItemButtons
              label={`${title} ${i + 1}`}
              up={i > 0 ? () => move(i, -1) : undefined}
              down={i < items.length - 1 ? () => move(i, 1) : undefined}
              remove={items.length > min ? () => set(items.filter((_, j) => j !== i)) : undefined}
            />
          </li>
        ))}
      </ol>
      <button type="button" disabled={items.length >= max} onClick={() => set([...items, initialValue(item, root)])}>
        {title} 더하기
      </button>
    </fieldset>
  );
}

export function ItemButtons({ label, up, down, remove }: { label: string; up?: () => void; down?: () => void; remove?: () => void }): ReactNode {
  // 단추 이름에 무엇을 옮기는지 함께(같은 '위로' 단추가 여럿 — WCAG 2.4.6·axe 는 막지 않지만 화면 읽기에서 구분)
  return (
    <span data-slot="item-buttons">
      <button type="button" disabled={!up} onClick={up} aria-label={`${label} 위로`}>
        위로
      </button>
      <button type="button" disabled={!down} onClick={down} aria-label={`${label} 아래로`}>
        아래로
      </button>
      <button type="button" disabled={!remove} onClick={remove} aria-label={`${label} 빼기`}>
        빼기
      </button>
    </span>
  );
}

function UnionField({ schema, root, value, onChange, path, errors, options, title, nullable, errId, own }: FieldProps & { title: string; nullable: boolean; errId: string; own: FieldError[] }) {
  const id = useId();
  const tag = schema.discriminator?.propertyName ?? "kind";
  const all = variants(schema, root);
  const current = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  const kind = current ? String(current[tag]) : "";
  const variant = all.find((v) => v.key === kind);
  return (
    <fieldset data-slot="field" data-kind="union">
      <legend>{title}</legend>
      <label htmlFor={id}>{variant?.schema.properties?.[tag]?.title ?? "종류"}</label>
      <select
        id={id}
        value={kind}
        aria-invalid={own.length > 0 || undefined}
        aria-describedby={own.length > 0 ? errId : undefined}
        onChange={(e) => {
          const next = all.find((v) => v.key === e.target.value);
          onChange(next ? initialValue(next.schema, root) : null);
        }}
      >
        {nullable && <option value="">없음</option>}
        {all.map((v) => (
          <option key={v.key} value={v.key}>
            {v.label}
          </option>
        ))}
      </select>
      <ErrorText errors={own} id={errId} />
      {variant && current && (
        // 꼬리표 합의 오류 위치에는 갈래 이름이 한 단 더 붙는다(Pydantic — `link.url.url`)
        <Properties schema={variant.schema} root={root} value={current} onChange={onChange} path={join(path, variant.key)} errors={errors} options={options} skip={tag} />
      )}
    </fieldset>
  );
}
