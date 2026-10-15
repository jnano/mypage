import type { FieldSpec } from "@/lib/admin/boardFields";

// 설정 칸 하나 — 칸 명세(lib/admin/boardFields·settingsFields)대로 입력 요소를 고른다. 라벨·도움말 연결(§13)
export function SettingField({ field, value, options }: { field: FieldSpec; value: string | boolean | string[]; options?: [string, string][] }) {
  const id = `f-${field.name.replace(".", "-")}`;
  const help = field.help ? <small id={`${id}-help`}>{field.help}</small> : null;
  const described = field.help ? { "aria-describedby": `${id}-help` } : {};
  if (field.type === "bool") {
    return (
      <p>
        <label>
          <input type="checkbox" name={field.name} defaultChecked={value === true} {...described} /> {field.label}
        </label>{" "}
        {help}
      </p>
    );
  }
  if (field.type === "multi") {
    return (
      <fieldset>
        <legend>{field.label}</legend>
        {(field.options ?? []).map(([v, label]) => (
          <label key={v}>
            <input type="checkbox" name={field.name} value={v} defaultChecked={(value as string[]).includes(v)} /> {label}
          </label>
        ))}
      </fieldset>
    );
  }
  const control =
    field.type === "select" ? (
      <select id={id} name={field.name} defaultValue={value as string} {...described}>
        {(options ?? field.options ?? []).map(([v, label]) => (
          <option key={v} value={v}>
            {label}
          </option>
        ))}
      </select>
    ) : field.type === "textarea" || field.type === "lines" ? (
      <textarea id={id} name={field.name} defaultValue={value as string} rows={field.type === "lines" ? 4 : 2} {...described} />
    ) : (
      <input id={id} name={field.name} defaultValue={value as string} inputMode={field.type === "text" ? undefined : "numeric"} {...described} />
    );
  return (
    <p>
      <label htmlFor={id}>{field.label}</label> {control} {help}
    </p>
  );
}
