import { create } from "zustand";

import type {
  AgentMode,
  ChatMessage,
  ChatMessageStatus,
  PendingAttachment,
} from "@/types/chat";

interface ChatState {
  /** Caller-controlled thread id (UUID) reused for the whole session. */
  threadId: string;
  mode: AgentMode;
  messages: ChatMessage[];
  /** Draft input value (kept in store so it survives navigation). */
  draft: string;
  /** Staged attachments displayed under the composer. */
  pendingAttachments: PendingAttachment[];
  /** True while a message is being streamed from the backend. */
  isSending: boolean;
  /** Last error surfaced at the page level (network failure, 4xx body). */
  error: string | null;

  setMode: (mode: AgentMode) => void;
  setDraft: (draft: string) => void;
  appendMessage: (message: ChatMessage) => void;
  patchMessage: (id: string, patch: Partial<ChatMessage>) => void;
  appendAssistantDelta: (id: string, delta: string) => void;
  finalizeMessage: (
    id: string,
    patch: { status: ChatMessageStatus; tokensSpent?: number; mode?: AgentMode },
  ) => void;
  addAttachment: (att: PendingAttachment) => void;
  removeAttachment: (id: string) => void;
  clearAttachments: () => void;
  setSending: (sending: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

function makeThreadId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `thread-${Math.random().toString(36).slice(2, 10)}`;
}

const INITIAL_MODE: AgentMode = "basic";

export const useChatStore = create<ChatState>((set) => ({
  threadId: makeThreadId(),
  mode: INITIAL_MODE,
  messages: [],
  draft: "",
  pendingAttachments: [],
  isSending: false,
  error: null,

  setMode: (mode) => set({ mode }),
  setDraft: (draft) => set({ draft }),
  appendMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),
  patchMessage: (id, patch) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),
  appendAssistantDelta: (id, delta) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id
          ? {
              ...m,
              content: `${m.content}${delta}`,
              status: m.status === "complete" ? m.status : "streaming",
            }
          : m,
      ),
    })),
  finalizeMessage: (id, patch) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),
  addAttachment: (att) =>
    set((state) => ({ pendingAttachments: [...state.pendingAttachments, att] })),
  removeAttachment: (id) =>
    set((state) => ({
      pendingAttachments: state.pendingAttachments.filter((a) => a.id !== id),
    })),
  clearAttachments: () => set({ pendingAttachments: [] }),
  setSending: (isSending) => set({ isSending }),
  setError: (error) => set({ error }),
  reset: () =>
    set({
      threadId: makeThreadId(),
      mode: INITIAL_MODE,
      messages: [],
      draft: "",
      pendingAttachments: [],
      isSending: false,
      error: null,
    }),
}));
