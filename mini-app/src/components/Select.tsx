import type { ChangeEvent } from "react";

export interface SelectOption<T extends string> {
  value: T;
  label: string;
}

interface SelectProps<T extends string> {
  value: T;
  onChange: (next: T) => void;
  options: ReadonlyArray<SelectOption<T>>;
  label: string;
  description?: string;
  id?: string;
  disabled?: boolean;
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  label,
  description,
  id,
  disabled = false,
}: SelectProps<T>): JSX.Element {
  const selectId = id ?? `select-${label.replace(/\s+/g, "-").toLowerCase()}`;
  const handleChange = (event: ChangeEvent<HTMLSelectElement>): void => {
    onChange(event.target.value as T);
  };
  return (
    <div className="py-2">
      <label htmlFor={selectId} className="block text-sm font-medium">
        {label}
      </label>
      {description ? <p className="mt-1 text-xs text-tg-hint">{description}</p> : null}
      <select
        id={selectId}
        value={value}
        onChange={handleChange}
        disabled={disabled}
        className="mt-2 w-full rounded-tg border border-tg-separator bg-tg-bg px-3 py-2 text-sm text-tg-text focus:outline-none focus:ring-2 focus:ring-tg-accent disabled:cursor-not-allowed disabled:opacity-50"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
