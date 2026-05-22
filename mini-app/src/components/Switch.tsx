interface SwitchProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
  id?: string;
}

export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled = false,
  id,
}: SwitchProps): JSX.Element {
  const inputId = id ?? `switch-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <label
      htmlFor={inputId}
      className={`flex items-start gap-3 py-2 ${disabled ? "opacity-50" : "cursor-pointer"}`}
    >
      <div className="flex-1">
        <div className="text-sm font-medium">{label}</div>
        {description ? <p className="mt-1 text-xs text-tg-hint">{description}</p> : null}
      </div>
      <span className="relative inline-flex h-6 w-11 flex-shrink-0 items-center">
        <input
          id={inputId}
          type="checkbox"
          role="switch"
          aria-label={label}
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="absolute inset-0 rounded-full bg-tg-secondary-bg transition-colors peer-checked:bg-tg-button" />
        <span className="absolute left-0.5 h-5 w-5 transform rounded-full bg-tg-button-text shadow transition-transform peer-checked:translate-x-5" />
      </span>
    </label>
  );
}
