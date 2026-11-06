import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Field, Toggle } from "../components/ui";
import { useApi } from "../lib/hooks";
import type { FieldSpec, Issue, NodeSpec } from "../lib/types";
import { isFieldVisible } from "./graph";

function JsonField({ value, onChange, disabled }: { value: any; onChange: (value: any) => void; disabled?: boolean }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    try {
      if (JSON.stringify(JSON.parse(text)) === JSON.stringify(value ?? {})) return;
    } catch {
      /* the local text is mid-edit */
    }
    setText(JSON.stringify(value ?? {}, null, 2));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <>
      <textarea
        className="field-mono min-h-[110px] resize-y"
        spellCheck={false}
        value={text}
        disabled={disabled}
        onChange={(e) => {
          setText(e.target.value);
          try {
            onChange(JSON.parse(e.target.value || "{}"));
            setError(null);
          } catch (exc) {
            setError((exc as Error).message);
          }
        }}
      />
      {error && <p className="mt-1 text-2xs text-[#F87171]">Invalid JSON: {error}</p>}
    </>
  );
}

function CredentialField({ field, value, onChange, disabled }: { field: FieldSpec; value: any; onChange: (value: any) => void; disabled?: boolean }) {
  const { data } = useApi<any[]>("/api/credentials");
  const options = (data || []).filter((c) => field.credential_types?.includes(c.type));
  return (
    <>
      <select className="field" value={value || ""} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        <option value="">{field.required ? "Choose a credential..." : "None"}</option>
        {options.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      {data && options.length === 0 && (
        <p className="mt-1 text-2xs text-faint">
          None saved yet.{" "}
          <Link to="/credentials" className="text-primary-hover hover:underline">
            Add a credential
          </Link>
        </p>
      )}
    </>
  );
}

function StringList({ value, onChange, placeholder, disabled }: { value: any; onChange: (value: string[]) => void; placeholder?: string; disabled?: boolean }) {
  const list: string[] = Array.isArray(value) ? value : typeof value === "string" && value ? value.split(",") : [];
  const [text, setText] = useState(list.join(", "));
  useEffect(() => {
    if (text.split(",").map((s) => s.trim()).filter(Boolean).join("|") !== list.join("|")) setText(list.join(", "));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(list)]);
  return (
    <input
      className="field"
      value={text}
      placeholder={placeholder || "Comma separated"}
      disabled={disabled}
      onChange={(e) => {
        setText(e.target.value);
        onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean));
      }}
    />
  );
}

function Cell({ column, value, onChange, disabled }: { column: FieldSpec; value: any; onChange: (value: any) => void; disabled?: boolean }) {
  if (column.type === "select") {
    return (
      <select aria-label={column.label} className="field" value={value ?? column.default ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {column.options?.map((o) => (
          <option key={String(o.value)} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }
  if (column.type === "boolean") {
    return (
      <label className="flex h-[30px] items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={value ?? column.default ?? false} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="accent-primary" />
        {column.label}
      </label>
    );
  }
  const asString = typeof value === "object" && value !== null ? JSON.stringify(value) : value ?? "";
  return <input aria-label={column.label} className={column.type === "expression" ? "field-mono" : "field"} value={String(asString)} placeholder={column.placeholder || column.label} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
}

function Rows({ field, value, onChange, disabled }: { field: FieldSpec; value: any; onChange: (value: any[]) => void; disabled?: boolean }) {
  const rows: any[] = Array.isArray(value) ? value : [];
  const blank = () => Object.fromEntries((field.columns || []).filter((c) => c.default !== null && c.default !== undefined).map((c) => [c.key, c.default]));
  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="rounded-md border border-line bg-base/40 p-2">
          <div className="space-y-1.5">
            {(field.columns || []).map((column) => (
              <Cell key={column.key} column={column} value={row?.[column.key]} disabled={disabled} onChange={(next) => onChange(rows.map((r, j) => (j === i ? { ...r, [column.key]: next } : r)))} />
            ))}
          </div>
          <div className="mt-1 flex justify-end">
            <Button size="sm" variant="ghost" disabled={disabled} aria-label={`Remove row ${i + 1}`} icon={<Trash2 size={12} />} onClick={() => onChange(rows.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </div>
        </div>
      ))}
      <Button size="sm" disabled={disabled} icon={<Plus size={13} />} onClick={() => onChange([...rows, blank()])}>
        Add
      </Button>
    </div>
  );
}

function KeyValue({ value, onChange, disabled }: { value: any; onChange: (value: any[]) => void; disabled?: boolean }) {
  const rows: any[] = Array.isArray(value) ? value : [];
  return (
    <div className="space-y-1.5">
      {rows.map((row, i) => (
        <div key={i} className="flex gap-1.5">
          <input aria-label="Name" className="field-mono w-2/5" placeholder="Name" value={row?.key ?? ""} disabled={disabled} onChange={(e) => onChange(rows.map((r, j) => (j === i ? { ...r, key: e.target.value } : r)))} />
          <input aria-label="Value" className="field-mono flex-1" placeholder="Value" value={row?.value ?? ""} disabled={disabled} onChange={(e) => onChange(rows.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)))} />
          <Button size="icon" variant="ghost" disabled={disabled} aria-label="Remove" icon={<Trash2 size={13} />} onClick={() => onChange(rows.filter((_, j) => j !== i))} />
        </div>
      ))}
      <Button size="sm" disabled={disabled} icon={<Plus size={13} />} onClick={() => onChange([...rows, { key: "", value: "" }])}>
        Add
      </Button>
    </div>
  );
}

function Control({ field, value, onChange, disabled }: { field: FieldSpec; value: any; onChange: (value: any) => void; disabled?: boolean }) {
  const id = `f-${field.key}`;
  switch (field.type) {
    case "text":
      return <textarea id={id} className="field min-h-[84px] resize-y" value={value ?? ""} placeholder={field.placeholder} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
    case "number":
      return <input id={id} type="text" inputMode="decimal" className="field" value={value ?? ""} placeholder={field.placeholder} disabled={disabled} onChange={(e) => onChange(e.target.value === "" ? null : Number.isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value))} />;
    case "select":
      return (
        <select id={id} className="field" value={String(value ?? field.default ?? "")} disabled={disabled} onChange={(e) => {
          const option = field.options?.find((o) => String(o.value) === e.target.value);
          onChange(option ? option.value : e.target.value);
        }}>
          {field.options?.map((o) => (
            <option key={String(o.value)} value={String(o.value)}>
              {o.label}
            </option>
          ))}
        </select>
      );
    case "expression":
      return <input id={id} className="field-mono" value={typeof value === "object" && value !== null ? JSON.stringify(value) : value ?? ""} placeholder={field.placeholder || "{{ input.field }}"} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
    case "json":
      return <JsonField value={value} onChange={onChange} disabled={disabled} />;
    case "credential":
      return <CredentialField field={field} value={value} onChange={onChange} disabled={disabled} />;
    case "string_list":
      return <StringList value={value} onChange={onChange} placeholder={field.placeholder} disabled={disabled} />;
    case "rows":
      return <Rows field={field} value={value} onChange={onChange} disabled={disabled} />;
    case "keyvalue":
      return <KeyValue value={value} onChange={onChange} disabled={disabled} />;
    default:
      return <input id={id} className="field" value={value ?? ""} placeholder={field.placeholder} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
  }
}

export function ConfigForm({ spec, config, onChange, issues, disabled }: { spec: NodeSpec; config: Record<string, any>; onChange: (config: Record<string, any>) => void; issues: Issue[]; disabled?: boolean }) {
  const visible = spec.fields.filter((f) => isFieldVisible(f, config, spec));
  if (visible.length === 0) return <p className="text-xs text-faint">This node has nothing to configure.</p>;
  return (
    <div className="space-y-3.5">
      {visible.map((field) => {
        const value = config[field.key] ?? field.default;
        const issue = issues.find((i) => i.field === field.key);
        if (field.type === "boolean") {
          return (
            <div key={field.key} className="flex items-center justify-between gap-3">
              <span className="text-xs font-medium text-muted">{field.label}</span>
              <Toggle checked={!!value} label={field.label} disabled={disabled} onChange={(next) => onChange({ ...config, [field.key]: next })} />
            </div>
          );
        }
        return (
          <Field
            key={field.key}
            htmlFor={`f-${field.key}`}
            label={
              <>
                {field.label}
                {field.required && <span className="ml-0.5 text-[#F87171]" title="Required">*</span>}
              </>
            }
            hint={field.help}
            error={issue?.message.replace(/^.*?: /, "")}
          >
            <Control field={field} value={value} disabled={disabled} onChange={(next) => onChange({ ...config, [field.key]: next })} />
          </Field>
        );
      })}
    </div>
  );
}
