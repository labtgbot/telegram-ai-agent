import { useEffect, useState } from "react";

import { Button } from "@/components/Button";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel: string;
  /** When set, the user must type this exact string before confirm is enabled. */
  requireText?: string;
  onConfirm: () => void;
  onCancel: () => void;
  confirming?: boolean;
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel,
  requireText,
  onConfirm,
  onCancel,
  confirming = false,
}: ConfirmDialogProps): JSX.Element | null {
  const [typed, setTyped] = useState("");

  useEffect(() => {
    if (!open) setTyped("");
  }, [open]);

  if (!open) return null;

  const canConfirm = !confirming && (!requireText || typed === requireText);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={(event) => {
        if (event.target === event.currentTarget && !confirming) {
          onCancel();
        }
      }}
    >
      <div className="w-full max-w-sm rounded-tg bg-tg-section-bg p-4 shadow-tg">
        <h3 id="confirm-dialog-title" className="text-base font-semibold">
          {title}
        </h3>
        <p className="mt-2 text-sm text-tg-hint">{body}</p>
        {requireText ? (
          <input
            type="text"
            aria-label={requireText}
            placeholder={requireText}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            className="mt-3 w-full rounded-tg border border-tg-separator bg-tg-bg px-3 py-2 text-sm text-tg-text focus:outline-none focus:ring-2 focus:ring-tg-accent"
          />
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={confirming}>
            {cancelLabel}
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={!canConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
