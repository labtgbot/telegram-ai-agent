import { useEffect, useRef } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";

import type { ChatMessage } from "@/types/chat";
import { MessageBubble } from "@/components/chat/MessageBubble";

interface MessageListProps {
  messages: ChatMessage[];
  emptyState?: JSX.Element;
}

export function MessageList({ messages, emptyState }: MessageListProps): JSX.Element {
  const ref = useRef<VirtuosoHandle | null>(null);
  const lastContent = messages[messages.length - 1]?.content;

  useEffect(() => {
    if (messages.length === 0) return;
    ref.current?.scrollToIndex({
      index: messages.length - 1,
      align: "end",
      behavior: "auto",
    });
  }, [messages.length, lastContent]);

  if (messages.length === 0 && emptyState) {
    return (
      <div className="flex h-full items-center justify-center" data-testid="chat-empty">
        {emptyState}
      </div>
    );
  }

  return (
    <Virtuoso
      ref={ref}
      data={messages}
      data-testid="chat-message-list"
      followOutput="smooth"
      itemContent={(_, message) => <MessageBubble key={message.id} message={message} />}
      className="h-full"
    />
  );
}
