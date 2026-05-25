import type { ReactElement } from "react";
import { useRef } from "react";

import { Button } from "@/components/Button";
import { ACTION_COST, type ChatAction, type PendingAttachment } from "@/types/chat";
import { readFileAsBase64 } from "@/services/chatApi";

const ACTION_ICON: Record<ChatAction, string> = {
  image: "🖼",
  video: "🎬",
  search: "🔎",
  document: "📄",
};

const ACTION_LABEL: Record<ChatAction, string> = {
  image: "Image",
  video: "Video",
  search: "Search",
  document: "Document",
};

interface ChatComposerProps {
  draft: string;
  estimatedCost: number;
  isSending: boolean;
  pendingAttachments: PendingAttachment[];
  onChangeDraft: (value: string) => void;
  onSubmit: () => void;
  onAction: (action: ChatAction) => void;
  onAttachmentAdded: (attachment: PendingAttachment) => void;
  onAttachmentRemoved: (id: string) => void;
}

export function ChatComposer({
  draft,
  estimatedCost,
  isSending,
  pendingAttachments,
  onChangeDraft,
  onSubmit,
  onAction,
  onAttachmentAdded,
  onAttachmentRemoved,
}: ChatComposerProps): ReactElement {
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const documentInputRef = useRef<HTMLInputElement | null>(null);

  const canSubmit = !isSending && (draft.trim().length > 0 || pendingAttachments.length > 0);

  return (
    <div className="border-t border-tg-separator bg-tg-header px-3 pb-3 pt-2">
      <div className="mb-2 grid grid-cols-4 gap-1">
        {(Object.keys(ACTION_ICON) as ChatAction[]).map((action) => (
          <button
            key={action}
            type="button"
            disabled={isSending}
            onClick={() => onAction(action)}
            data-testid={`action-${action}`}
            className="flex flex-col items-center gap-0.5 rounded-tg bg-tg-secondary-bg px-2 py-1.5 text-[11px] text-tg-text transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            title={`${ACTION_LABEL[action]} · ${ACTION_COST[action]} tokens`}
          >
            <span aria-hidden className="text-base">
              {ACTION_ICON[action]}
            </span>
            <span className="font-medium">{ACTION_LABEL[action]}</span>
            <span className="text-[10px] text-tg-hint">{ACTION_COST[action]}t</span>
          </button>
        ))}
      </div>

      {pendingAttachments.length > 0 ? (
        <ul className="mb-2 flex gap-2 overflow-x-auto" data-testid="pending-attachments">
          {pendingAttachments.map((att) => (
            <li key={att.id} className="relative shrink-0 rounded-tg bg-tg-secondary-bg p-1">
              {att.kind === "image" ? (
                <img
                  src={att.previewUrl}
                  alt={att.name}
                  className="h-12 w-12 rounded object-cover"
                />
              ) : (
                <div className="flex h-12 w-24 items-center gap-1 px-1 text-[11px]">
                  <span aria-hidden>📄</span>
                  <span className="truncate">{att.name}</span>
                </div>
              )}
              <button
                type="button"
                aria-label={`Remove ${att.name}`}
                onClick={() => onAttachmentRemoved(att.id)}
                className="absolute -right-1 -top-1 h-4 w-4 rounded-full bg-tg-destructive text-[10px] text-tg-button-text"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="flex items-end gap-2">
        <textarea
          aria-label="Message"
          value={draft}
          onChange={(e) => onChangeDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSubmit) onSubmit();
            }
          }}
          rows={2}
          placeholder="Ask anything…"
          data-testid="chat-input"
          className="min-h-[44px] flex-1 resize-none rounded-tg border border-tg-separator bg-tg-bg px-3 py-2 text-sm text-tg-text placeholder:text-tg-hint focus:border-tg-link focus:outline-none"
        />
        <div className="flex flex-col items-end gap-1">
          <Button
            onClick={() => canSubmit && onSubmit()}
            disabled={!canSubmit}
            data-testid="chat-send"
          >
            {isSending ? "…" : "Send"}
          </Button>
          <span className="text-[10px] text-tg-hint" data-testid="cost-indicator">
            ≈ {estimatedCost} tokens
          </span>
        </div>
      </div>

      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        hidden
        data-testid="image-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            void handleFileSelected(file, "image", onAttachmentAdded);
            e.target.value = "";
          }
        }}
      />
      <input
        ref={documentInputRef}
        type="file"
        accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
        hidden
        data-testid="document-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            void handleFileSelected(file, "document", onAttachmentAdded);
            e.target.value = "";
          }
        }}
      />

      {/* Internal triggers exposed for parent via custom events. */}
      <div hidden>
        <button
          type="button"
          data-testid="pick-image"
          onClick={() => imageInputRef.current?.click()}
        />
        <button
          type="button"
          data-testid="pick-document"
          onClick={() => documentInputRef.current?.click()}
        />
      </div>
    </div>
  );
}

async function handleFileSelected(
  file: File,
  kind: "image" | "document",
  onAdded: (att: PendingAttachment) => void,
): Promise<void> {
  const base64 = await readFileAsBase64(file);
  const previewUrl =
    typeof URL !== "undefined" && "createObjectURL" in URL ? URL.createObjectURL(file) : "";
  onAdded({
    id: `att-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    kind,
    name: file.name,
    sizeBytes: file.size,
    mimeType: file.type,
    base64,
    previewUrl,
  });
}
