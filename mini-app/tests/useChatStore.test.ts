import { beforeEach, describe, expect, it } from "vitest";

import { useChatStore } from "@/store/useChatStore";

describe("useChatStore", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
  });

  it("starts with sensible defaults", () => {
    const s = useChatStore.getState();
    expect(s.mode).toBe("basic");
    expect(s.messages).toEqual([]);
    expect(s.draft).toBe("");
    expect(s.isSending).toBe(false);
    expect(s.pendingAttachments).toEqual([]);
    expect(s.threadId).toMatch(/.+/);
  });

  it("switches mode and persists draft", () => {
    useChatStore.getState().setMode("advanced");
    useChatStore.getState().setDraft("hello");
    expect(useChatStore.getState().mode).toBe("advanced");
    expect(useChatStore.getState().draft).toBe("hello");
  });

  it("appends + streams deltas into an assistant message", () => {
    const id = "a-1";
    useChatStore.getState().appendMessage({
      id,
      role: "assistant",
      content: "",
      createdAt: 0,
      status: "pending",
    });
    useChatStore.getState().appendAssistantDelta(id, "Hel");
    useChatStore.getState().appendAssistantDelta(id, "lo");

    const message = useChatStore.getState().messages[0]!;
    expect(message.content).toBe("Hello");
    expect(message.status).toBe("streaming");

    useChatStore
      .getState()
      .finalizeMessage(id, { status: "complete", tokensSpent: 7, mode: "basic" });
    const final = useChatStore.getState().messages[0]!;
    expect(final.status).toBe("complete");
    expect(final.tokensSpent).toBe(7);
  });

  it("manages staged attachments", () => {
    useChatStore.getState().addAttachment({
      id: "att-1",
      kind: "image",
      name: "cat.jpg",
      sizeBytes: 1024,
      mimeType: "image/jpeg",
      base64: "AAA",
      previewUrl: "blob:cat",
    });
    expect(useChatStore.getState().pendingAttachments).toHaveLength(1);

    useChatStore.getState().removeAttachment("att-1");
    expect(useChatStore.getState().pendingAttachments).toHaveLength(0);
  });

  it("reset() generates a fresh thread id and clears state", () => {
    const before = useChatStore.getState().threadId;
    useChatStore.getState().setDraft("draft");
    useChatStore.getState().setMode("autonomous_agent");
    useChatStore.getState().reset();
    const after = useChatStore.getState().threadId;
    expect(after).not.toEqual(before);
    expect(useChatStore.getState().draft).toBe("");
    expect(useChatStore.getState().mode).toBe("basic");
  });
});
