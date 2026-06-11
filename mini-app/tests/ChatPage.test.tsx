import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

import { ChatPage } from "@/pages/ChatPage";
import { useChatStore } from "@/store/useChatStore";
import { useUserStore } from "@/store/useUserStore";
import type { StreamHandlers, SendMessageRequest } from "@/services/chatApi";
import type * as ChatApiModule from "@/services/chatApi";

vi.mock("react-virtuoso", () => ({
  Virtuoso: ({
    data,
    itemContent,
  }: {
    data: unknown[];
    itemContent: (index: number, item: unknown) => ReactNode;
  }) => (
    <div data-testid="chat-message-list">{data.map((item, index) => itemContent(index, item))}</div>
  ),
}));

vi.mock("@/services/chatApi", async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ChatApiModule;
  return {
    ...actual,
    streamTextGeneration: vi.fn(async (_request: SendMessageRequest, handlers: StreamHandlers) => {
      handlers.onStart?.("req-1");
      handlers.onDelta?.("Hello");
      handlers.onFinal?.({
        event: "final",
        text: "Hello",
        tokens_spent: 1,
        new_balance: 41,
        mode: "basic",
        request_id: "req-1",
        thread_id: "thread-1",
      });
    }),
  };
});

describe("ChatPage", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
    useUserStore.getState().reset();
    useUserStore.getState().setBalance(42);
  });

  it("updates the displayed balance from the final text generation event", async () => {
    render(<ChatPage />);

    await userEvent.type(screen.getByTestId("chat-input"), "hello");
    await userEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() => expect(useUserStore.getState().balance).toBe(41));
  });
});
