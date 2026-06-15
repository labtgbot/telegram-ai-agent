import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

import { ChatPage } from "@/pages/ChatPage";
import { useChatStore } from "@/store/useChatStore";
import { useUserStore } from "@/store/useUserStore";
import type { StreamHandlers, SendMessageRequest } from "@/services/chatApi";
import type * as ChatApiModule from "@/services/chatApi";

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

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
  let objectUrlSequence = 0;

  beforeEach(() => {
    objectUrlSequence = 0;
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn((blob: Blob) => {
        objectUrlSequence += 1;
        const name = blob instanceof File && blob.name ? blob.name : "preview";
        return `blob:${name}-${objectUrlSequence}`;
      }),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    useChatStore.getState().reset();
    useUserStore.getState().reset();
    useUserStore.getState().setBalance(42);
  });

  afterEach(() => {
    if (originalCreateObjectURL) {
      Object.defineProperty(URL, "createObjectURL", {
        configurable: true,
        writable: true,
        value: originalCreateObjectURL,
      });
    } else {
      delete (URL as unknown as { createObjectURL?: unknown }).createObjectURL;
    }

    if (originalRevokeObjectURL) {
      Object.defineProperty(URL, "revokeObjectURL", {
        configurable: true,
        writable: true,
        value: originalRevokeObjectURL,
      });
    } else {
      delete (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL;
    }
  });

  it("updates the displayed balance from the final text generation event", async () => {
    render(<ChatPage />);

    await userEvent.type(screen.getByTestId("chat-input"), "hello");
    await userEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() => expect(useUserStore.getState().balance).toBe(41));
  });

  it("revokes the object URL when a selected attachment is removed", async () => {
    render(<ChatPage />);

    fireEvent.change(screen.getByTestId("image-input"), {
      target: {
        files: [new File(["image"], "cat.png", { type: "image/png" })],
      },
    });

    await screen.findByRole("img", { name: "cat.png" });
    await userEvent.click(screen.getByRole("button", { name: "Remove cat.png" }));

    await waitFor(() => {
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:cat.png-1");
    });
  });

  it("revokes the object URL when a pasted attachment is removed", async () => {
    const { container } = render(<ChatPage />);
    const chatPage = container.firstElementChild;
    expect(chatPage).toBeInstanceOf(HTMLElement);

    fireEvent.paste(chatPage as HTMLElement, {
      clipboardData: {
        files: [new File(["image"], "paste.png", { type: "image/png" })],
      },
    });

    await screen.findByRole("img", { name: "paste.png" });
    await userEvent.click(screen.getByRole("button", { name: "Remove paste.png" }));

    await waitFor(() => {
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:paste.png-1");
    });
  });

  it("revokes tracked object URLs on unmount", async () => {
    const { unmount } = render(<ChatPage />);

    fireEvent.change(screen.getByTestId("image-input"), {
      target: {
        files: [new File(["image"], "unmount.png", { type: "image/png" })],
      },
    });

    await screen.findByRole("img", { name: "unmount.png" });

    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:unmount.png-1");
  });
});
