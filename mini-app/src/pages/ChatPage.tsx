import type { ReactElement } from "react";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { MessageList } from "@/components/chat/MessageList";
import { ModeSwitcher } from "@/components/chat/ModeSwitcher";
import {
  analyseDocument,
  estimateMessageCost,
  generateImage,
  readFileAsBase64,
  runWebSearch,
  streamTextGeneration,
  submitVideoJob,
} from "@/services/chatApi";
import { useChatStore } from "@/store/useChatStore";
import { useUserStore } from "@/store/useUserStore";
import {
  ACTION_COST,
  MODE_DESCRIPTION,
  MODE_LABEL,
  type ChatAction,
  type ChatAttachment,
  type ChatMessage,
  type PendingAttachment,
} from "@/types/chat";

function makeId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function isObjectUrl(url: string | undefined): url is string {
  return typeof url === "string" && url.startsWith("blob:");
}

function revokeObjectUrl(url: string): void {
  if (typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
    URL.revokeObjectURL(url);
  }
}

export function ChatPage(): ReactElement {
  const user = useUserStore((s) => s.user);
  const setBalance = useUserStore((s) => s.setBalance);
  const threadId = useChatStore((s) => s.threadId);
  const mode = useChatStore((s) => s.mode);
  const messages = useChatStore((s) => s.messages);
  const draft = useChatStore((s) => s.draft);
  const pendingAttachments = useChatStore((s) => s.pendingAttachments);
  const isSending = useChatStore((s) => s.isSending);
  const error = useChatStore((s) => s.error);
  const setMode = useChatStore((s) => s.setMode);
  const setDraft = useChatStore((s) => s.setDraft);
  const appendMessage = useChatStore((s) => s.appendMessage);
  const appendAssistantDelta = useChatStore((s) => s.appendAssistantDelta);
  const finalizeMessage = useChatStore((s) => s.finalizeMessage);
  const patchMessage = useChatStore((s) => s.patchMessage);
  const addAttachment = useChatStore((s) => s.addAttachment);
  const removeAttachment = useChatStore((s) => s.removeAttachment);
  const clearAttachments = useChatStore((s) => s.clearAttachments);
  const setSending = useChatStore((s) => s.setSending);
  const setError = useChatStore((s) => s.setError);

  const abortRef = useRef<AbortController | null>(null);
  const trackedObjectUrlsRef = useRef<Set<string>>(new Set());

  const attachmentCost = useMemo(
    () =>
      pendingAttachments.reduce(
        (sum, att) => sum + (att.kind === "image" ? ACTION_COST.image : ACTION_COST.document),
        0,
      ),
    [pendingAttachments],
  );

  const estimatedCost = estimateMessageCost(mode) + attachmentCost;

  const activeObjectUrls = useMemo(() => {
    const urls = new Set<string>();
    for (const att of pendingAttachments) {
      if (isObjectUrl(att.previewUrl)) urls.add(att.previewUrl);
    }
    for (const message of messages) {
      for (const att of message.attachments ?? []) {
        if (isObjectUrl(att.url)) urls.add(att.url);
      }
    }
    return urls;
  }, [messages, pendingAttachments]);

  useEffect(() => {
    const tracked = trackedObjectUrlsRef.current;
    for (const url of activeObjectUrls) {
      tracked.add(url);
    }
    for (const url of Array.from(tracked)) {
      if (!activeObjectUrls.has(url)) {
        revokeObjectUrl(url);
        tracked.delete(url);
      }
    }
  }, [activeObjectUrls]);

  useEffect(() => {
    const tracked = trackedObjectUrlsRef.current;
    return () => {
      for (const url of tracked) {
        revokeObjectUrl(url);
      }
      tracked.clear();
    };
  }, []);

  const submitText = useCallback(async () => {
    const prompt = draft.trim();
    if (!prompt && pendingAttachments.length === 0) return;

    setError(null);

    // Carry pending attachments into the user message bubble so they show up
    // in history; we'll process documents/images via dedicated endpoints
    // alongside the streaming text call.
    const userAttachments: ChatAttachment[] = pendingAttachments.map((att) => ({
      id: att.id,
      kind: att.kind,
      url: att.previewUrl,
      name: att.name,
      mimeType: att.mimeType,
      sizeBytes: att.sizeBytes,
    }));

    const userMessage: ChatMessage = {
      id: makeId("u"),
      role: "user",
      content: prompt,
      createdAt: Date.now(),
      status: "complete",
      mode,
      attachments: userAttachments.length > 0 ? userAttachments : undefined,
      tokensSpent: estimatedCost,
    };
    appendMessage(userMessage);

    const assistantId = makeId("a");
    appendMessage({
      id: assistantId,
      role: "assistant",
      content: "",
      createdAt: Date.now(),
      status: "pending",
      mode,
    });

    setDraft("");
    clearAttachments();
    setSending(true);

    // Run document analysis up-front (sequentially per attachment) so its
    // extracted text can be referenced by the streaming text answer.
    const documentContexts: string[] = [];
    for (const att of pendingAttachments) {
      if (att.kind !== "document") continue;
      try {
        const result = await analyseDocument({
          base64: att.base64,
          filename: att.name,
          fileSizeBytes: att.sizeBytes,
          question: prompt || undefined,
        });
        documentContexts.push(
          `Document "${att.name}" (${result.format}) summary:\n${result.summary ?? result.text.slice(0, 2000)}`,
        );
        setBalance(result.new_balance);
      } catch (err) {
        documentContexts.push(`Document "${att.name}" could not be analysed.`);
        console.warn("document analysis failed", err);
      }
    }

    const effectivePrompt =
      documentContexts.length > 0 ? `${prompt}\n\n---\n${documentContexts.join("\n\n")}` : prompt;

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamTextGeneration(
        {
          prompt: effectivePrompt || "Summarise the attached file.",
          mode,
          threadId,
          signal: controller.signal,
        },
        {
          onStart: () => patchMessage(assistantId, { status: "streaming" }),
          onDelta: (delta) => appendAssistantDelta(assistantId, delta),
          onFinal: (final) => {
            setBalance(final.new_balance);
            finalizeMessage(assistantId, {
              status: "complete",
              tokensSpent: final.tokens_spent,
              mode: final.mode,
            });
          },
          onError: (e) => {
            finalizeMessage(assistantId, { status: "error" });
            patchMessage(assistantId, { error: e.message });
            setError(e.message);
          },
        },
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      finalizeMessage(assistantId, { status: "error" });
      patchMessage(assistantId, { error: message });
      setError(message);
    } finally {
      setSending(false);
      abortRef.current = null;
    }
  }, [
    appendAssistantDelta,
    appendMessage,
    clearAttachments,
    draft,
    estimatedCost,
    finalizeMessage,
    mode,
    patchMessage,
    pendingAttachments,
    setBalance,
    setDraft,
    setError,
    setSending,
    threadId,
  ]);

  const handleAction = useCallback(
    async (action: ChatAction) => {
      switch (action) {
        case "image": {
          const prompt = draft.trim();
          if (!prompt) {
            setError("Type an image prompt first.");
            return;
          }
          setSending(true);
          setError(null);
          const userMessage: ChatMessage = {
            id: makeId("u"),
            role: "user",
            content: `/image ${prompt}`,
            createdAt: Date.now(),
            status: "complete",
            tokensSpent: ACTION_COST.image,
          };
          appendMessage(userMessage);
          setDraft("");
          const assistantId = makeId("a");
          appendMessage({
            id: assistantId,
            role: "assistant",
            content: "",
            createdAt: Date.now(),
            status: "pending",
          });
          try {
            const result = await generateImage(prompt);
            setBalance(result.new_balance);
            finalizeMessage(assistantId, {
              status: "complete",
              tokensSpent: result.tokens_spent,
            });
            patchMessage(assistantId, {
              content: `Generated image for: ${result.prompt}`,
              attachments: [
                {
                  id: makeId("att"),
                  kind: "image",
                  url: result.result_url,
                  caption: result.prompt,
                },
              ],
            });
          } catch (err) {
            const message = err instanceof Error ? err.message : "Unknown error";
            finalizeMessage(assistantId, { status: "error" });
            patchMessage(assistantId, { error: message });
            setError(message);
          } finally {
            setSending(false);
          }
          return;
        }
        case "video": {
          const prompt = draft.trim();
          if (!prompt) {
            setError("Type a video prompt first.");
            return;
          }
          setSending(true);
          setError(null);
          appendMessage({
            id: makeId("u"),
            role: "user",
            content: `/video ${prompt}`,
            createdAt: Date.now(),
            status: "complete",
            tokensSpent: ACTION_COST.video,
          });
          setDraft("");
          const assistantId = makeId("a");
          appendMessage({
            id: assistantId,
            role: "assistant",
            content: "",
            createdAt: Date.now(),
            status: "pending",
          });
          try {
            const job = await submitVideoJob(prompt);
            if (typeof job.new_balance === "number") {
              setBalance(job.new_balance);
            }
            patchMessage(assistantId, {
              content:
                job.status === "succeeded" && job.result_url
                  ? `Video ready (job #${job.job_id}).`
                  : `Video job #${job.job_id} submitted (status: ${job.status}). Poll back for the result.`,
              attachments: job.result_url
                ? [
                    {
                      id: makeId("att"),
                      kind: "video",
                      url: job.result_url,
                      caption: prompt,
                    },
                  ]
                : undefined,
            });
            finalizeMessage(assistantId, {
              status: "complete",
              tokensSpent: job.tokens_cost,
            });
          } catch (err) {
            const message = err instanceof Error ? err.message : "Unknown error";
            finalizeMessage(assistantId, { status: "error" });
            patchMessage(assistantId, { error: message });
            setError(message);
          } finally {
            setSending(false);
          }
          return;
        }
        case "search": {
          const query = draft.trim();
          if (!query) {
            setError("Type a search query first.");
            return;
          }
          setSending(true);
          setError(null);
          appendMessage({
            id: makeId("u"),
            role: "user",
            content: `/search ${query}`,
            createdAt: Date.now(),
            status: "complete",
            tokensSpent: ACTION_COST.search,
          });
          setDraft("");
          const assistantId = makeId("a");
          appendMessage({
            id: assistantId,
            role: "assistant",
            content: "",
            createdAt: Date.now(),
            status: "pending",
          });
          try {
            const res = await runWebSearch(query);
            setBalance(res.new_balance);
            patchMessage(assistantId, {
              content: res.summary ?? `Found ${res.results.length} results for "${query}".`,
              attachments: [
                {
                  id: makeId("att"),
                  kind: "search_results",
                  data: res.results,
                },
              ],
            });
            finalizeMessage(assistantId, {
              status: "complete",
              tokensSpent: res.tokens_spent,
            });
          } catch (err) {
            const message = err instanceof Error ? err.message : "Unknown error";
            finalizeMessage(assistantId, { status: "error" });
            patchMessage(assistantId, { error: message });
            setError(message);
          } finally {
            setSending(false);
          }
          return;
        }
        case "document": {
          const input = document.querySelector<HTMLButtonElement>('[data-testid="pick-document"]');
          input?.click();
          return;
        }
        default:
          return;
      }
    },
    [
      appendMessage,
      draft,
      finalizeMessage,
      patchMessage,
      setBalance,
      setDraft,
      setError,
      setSending,
    ],
  );

  const handleAttachmentAdded = useCallback(
    (att: PendingAttachment) => addAttachment(att),
    [addAttachment],
  );

  const handleAttachmentRemoved = useCallback(
    (id: string) => removeAttachment(id),
    [removeAttachment],
  );

  // Image button: shortcut to open file picker (alternative to image-prompt).
  const handleActionDispatch = useCallback(
    (action: ChatAction) => {
      if (action === "image" && draft.trim().length === 0) {
        const input = document.querySelector<HTMLButtonElement>('[data-testid="pick-image"]');
        input?.click();
        return;
      }
      void handleAction(action);
    },
    [draft, handleAction],
  );

  // Allow attaching a captured image via clipboard upload flow.
  const handleClipboardPaste = useCallback(
    async (e: React.ClipboardEvent<HTMLDivElement>) => {
      const file = Array.from(e.clipboardData.files).find((f) => f.type.startsWith("image/"));
      if (!file) return;
      const base64 = await readFileAsBase64(file);
      addAttachment({
        id: makeId("att"),
        kind: "image",
        name: file.name || "pasted-image",
        sizeBytes: file.size,
        mimeType: file.type,
        base64,
        previewUrl: URL.createObjectURL(file),
      });
    },
    [addAttachment],
  );

  return (
    <div
      className="-mx-4 -my-4 flex h-[calc(100dvh-7.5rem)] flex-col"
      onPaste={handleClipboardPaste}
    >
      <div className="border-b border-tg-separator bg-tg-header px-3 py-2">
        <ModeSwitcher value={mode} onChange={setMode} disabled={isSending} />
        <p className="mt-1 text-[11px] text-tg-hint" data-testid="mode-description">
          {MODE_LABEL[mode]} · {MODE_DESCRIPTION[mode]}
        </p>
      </div>

      <div className="flex-1 overflow-hidden px-3 py-2">
        <MessageList
          messages={messages}
          emptyState={<EmptyState name={user?.first_name ?? user?.username ?? null} />}
        />
      </div>

      {error ? (
        <div
          role="alert"
          className="mx-3 mb-2 rounded-tg bg-tg-destructive/15 px-3 py-2 text-xs text-tg-destructive"
        >
          {error}
        </div>
      ) : null}

      <ChatComposer
        draft={draft}
        isSending={isSending}
        estimatedCost={estimatedCost}
        pendingAttachments={pendingAttachments}
        onChangeDraft={setDraft}
        onSubmit={() => void submitText()}
        onAction={handleActionDispatch}
        onAttachmentAdded={handleAttachmentAdded}
        onAttachmentRemoved={handleAttachmentRemoved}
      />
    </div>
  );
}

function EmptyState({ name }: { name: string | null }): ReactElement {
  return (
    <div className="max-w-md text-center text-sm text-tg-hint">
      <p className="mb-2 text-base font-semibold text-tg-text">Hi{name ? `, ${name}` : ""} 👋</p>
      <p>
        Pick a mode above and start chatting. Use the buttons below to generate images, videos, run
        a web search or analyse a document.
      </p>
    </div>
  );
}
