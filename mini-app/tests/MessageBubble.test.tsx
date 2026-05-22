import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { MessageBubble } from "@/components/chat/MessageBubble";

describe("MessageBubble", () => {
  it("renders user content as markdown", () => {
    render(
      <MessageBubble
        message={{
          id: "u-1",
          role: "user",
          content: "Hello **world**",
          createdAt: 0,
          status: "complete",
          mode: "basic",
        }}
      />,
    );
    const strong = screen.getByText("world");
    expect(strong.tagName).toBe("STRONG");
    expect(screen.getByTestId("message-user")).toBeInTheDocument();
  });

  it("renders code fences with a <code> block", () => {
    render(
      <MessageBubble
        message={{
          id: "a-1",
          role: "assistant",
          content: "```ts\nconst x = 1;\n```",
          createdAt: 0,
          status: "complete",
        }}
      />,
    );
    const code = screen.getByText(/const x = 1;/);
    expect(code).toBeInTheDocument();
  });

  it("renders an image attachment", () => {
    render(
      <MessageBubble
        message={{
          id: "a-2",
          role: "assistant",
          content: "Here is the image",
          createdAt: 0,
          status: "complete",
          attachments: [
            {
              id: "att-1",
              kind: "image",
              url: "https://example.com/cat.jpg",
              caption: "A cat",
            },
          ],
        }}
      />,
    );
    const img = screen.getByRole("img", { name: "A cat" });
    expect(img).toHaveAttribute("src", "https://example.com/cat.jpg");
  });

  it("renders search results as a structured list", () => {
    render(
      <MessageBubble
        message={{
          id: "a-3",
          role: "assistant",
          content: "Results:",
          createdAt: 0,
          status: "complete",
          attachments: [
            {
              id: "att-2",
              kind: "search_results",
              data: [
                { title: "Telegram", url: "https://telegram.org", snippet: "Chats." },
              ],
            },
          ],
        }}
      />,
    );
    const link = screen.getByRole("link", { name: "Telegram" });
    expect(link).toHaveAttribute("href", "https://telegram.org");
  });

  it("renders typing indicator when status is pending", () => {
    render(
      <MessageBubble
        message={{
          id: "a-pending",
          role: "assistant",
          content: "",
          createdAt: 0,
          status: "pending",
        }}
      />,
    );
    expect(screen.getByLabelText("Assistant is typing")).toBeInTheDocument();
  });
});
