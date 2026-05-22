import {
  MODE_COST,
  MODE_DESCRIPTION,
  MODE_LABEL,
  type AgentMode,
} from "@/types/chat";

const MODES: AgentMode[] = ["basic", "advanced", "autonomous_agent"];

interface ModeSwitcherProps {
  value: AgentMode;
  onChange: (mode: AgentMode) => void;
  disabled?: boolean;
}

export function ModeSwitcher({ value, onChange, disabled }: ModeSwitcherProps): JSX.Element {
  return (
    <div
      role="radiogroup"
      aria-label="Agent mode"
      className="flex gap-1 rounded-tg bg-tg-secondary-bg p-1 text-xs"
    >
      {MODES.map((mode) => {
        const selected = mode === value;
        return (
          <button
            key={mode}
            role="radio"
            aria-checked={selected}
            type="button"
            disabled={disabled}
            onClick={() => onChange(mode)}
            title={MODE_DESCRIPTION[mode]}
            data-testid={`mode-${mode}`}
            className={`flex-1 rounded-tg px-2 py-1 text-center transition-colors ${
              selected
                ? "bg-tg-button text-tg-button-text shadow-tg"
                : "text-tg-hint hover:text-tg-text"
            } disabled:cursor-not-allowed disabled:opacity-50`}
          >
            <span className="block font-medium">{MODE_LABEL[mode]}</span>
            <span className="block text-[10px] opacity-80">
              {MODE_COST[mode]} {MODE_COST[mode] === 1 ? "token" : "tokens"}
            </span>
          </button>
        );
      })}
    </div>
  );
}
