import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ChatComposer } from "@/components/chat/ChatComposer";

function renderComposer(overrides: Partial<React.ComponentProps<typeof ChatComposer>> = {}) {
  const props: React.ComponentProps<typeof ChatComposer> = {
    draft: "",
    estimatedCost: 1,
    isSending: false,
    pendingAttachments: [],
    onChangeDraft: vi.fn(),
    onSubmit: vi.fn(),
    onAction: vi.fn(),
    onAttachmentAdded: vi.fn(),
    onAttachmentRemoved: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<ChatComposer {...props} />) };
}

describe("ChatComposer", () => {
  it("disables Send when draft is empty and no attachments", () => {
    renderComposer();
    expect(screen.getByTestId("chat-send")).toBeDisabled();
  });

  it("enables Send when there is draft text", () => {
    renderComposer({ draft: "hi" });
    expect(screen.getByTestId("chat-send")).not.toBeDisabled();
  });

  it("submits on Enter without Shift", () => {
    const onSubmit = vi.fn();
    renderComposer({ draft: "hello", onSubmit });
    const input = screen.getByTestId("chat-input");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalled();
  });

  it("does not submit on Shift+Enter", () => {
    const onSubmit = vi.fn();
    renderComposer({ draft: "hello", onSubmit });
    const input = screen.getByTestId("chat-input");
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("fires onAction for each side button", () => {
    const onAction = vi.fn();
    renderComposer({ onAction });
    fireEvent.click(screen.getByTestId("action-image"));
    fireEvent.click(screen.getByTestId("action-video"));
    fireEvent.click(screen.getByTestId("action-search"));
    fireEvent.click(screen.getByTestId("action-document"));
    expect(onAction.mock.calls.map((c) => c[0])).toEqual([
      "image",
      "video",
      "search",
      "document",
    ]);
  });

  it("renders the cost indicator", () => {
    renderComposer({ estimatedCost: 7 });
    expect(screen.getByTestId("cost-indicator")).toHaveTextContent("≈ 7 tokens");
  });

  it("removes a staged attachment", () => {
    const onAttachmentRemoved = vi.fn();
    renderComposer({
      pendingAttachments: [
        {
          id: "att-1",
          kind: "image",
          name: "cat.jpg",
          sizeBytes: 100,
          mimeType: "image/jpeg",
          base64: "AAA",
          previewUrl: "blob:cat",
        },
      ],
      onAttachmentRemoved,
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove cat.jpg" }));
    expect(onAttachmentRemoved).toHaveBeenCalledWith("att-1");
  });
});
