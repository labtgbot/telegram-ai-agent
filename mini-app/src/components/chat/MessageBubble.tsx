import type { ReactElement } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ChatAttachment, ChatMessage } from "@/types/chat";
import { MODE_LABEL } from "@/types/chat";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps): ReactElement {
  const isUser = message.role === "user";
  const align = isUser ? "items-end" : "items-start";
  const bubbleColor = isUser
    ? "bg-tg-button text-tg-button-text"
    : "bg-tg-secondary-bg text-tg-text";
  const isError = message.status === "error";

  return (
    <div className={`flex flex-col ${align} my-2`} data-testid={`message-${message.role}`}>
      <div
        className={`max-w-[85%] rounded-tg px-3 py-2 text-sm shadow-tg ${bubbleColor} ${
          isError ? "border border-tg-destructive" : ""
        }`}
      >
        {message.content ? (
          <MarkdownBody content={message.content} variant={isUser ? "inverted" : "default"} />
        ) : message.status === "pending" || message.status === "streaming" ? (
          <TypingDots />
        ) : null}

        {message.attachments?.map((att) => (
          <AttachmentView key={att.id} attachment={att} />
        ))}

        {isError && message.error ? (
          <p className="mt-1 text-xs text-tg-destructive">{message.error}</p>
        ) : null}
      </div>

      <div className="mt-1 flex gap-2 px-1 text-[10px] uppercase tracking-wide text-tg-hint">
        {message.mode ? <span data-testid="message-mode">{MODE_LABEL[message.mode]}</span> : null}
        {typeof message.tokensSpent === "number" && message.tokensSpent > 0 ? (
          <span>· {message.tokensSpent} tokens</span>
        ) : null}
      </div>
    </div>
  );
}

interface MarkdownBodyProps {
  content: string;
  variant: "default" | "inverted";
}

function MarkdownBody({ content, variant }: MarkdownBodyProps): ReactElement {
  const codeBg = variant === "inverted" ? "bg-black/30" : "bg-tg-bg/60";
  const linkClass =
    variant === "inverted" ? "underline text-tg-button-text" : "underline text-tg-link";
  return (
    <div className="prose-tg break-words text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children, ...rest }) => (
            <a
              {...rest}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className={linkClass}
            >
              {children}
            </a>
          ),
          code: ({ className, children, ...rest }) => {
            const isInline = !className?.startsWith("language-");
            if (isInline) {
              return (
                <code {...rest} className={`${codeBg} rounded px-1 py-0.5 font-mono text-[12px]`}>
                  {children}
                </code>
              );
            }
            return (
              <code
                {...rest}
                className={`${className ?? ""} block font-mono text-[12px] leading-snug`}
              >
                {children}
              </code>
            );
          },
          pre: ({ children, ...rest }) => (
            <pre
              {...rest}
              className={`${codeBg} my-2 overflow-x-auto rounded-tg p-2 font-mono text-[12px]`}
            >
              {children}
            </pre>
          ),
          img: ({ src, alt, ...rest }) => (
            <img
              {...rest}
              src={src}
              alt={alt ?? ""}
              loading="lazy"
              className="my-2 max-h-72 rounded-tg"
            />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function TypingDots(): ReactElement {
  return (
    <span aria-label="Assistant is typing" className="inline-flex gap-1 align-middle">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-tg-hint" />
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-tg-hint [animation-delay:120ms]" />
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-tg-hint [animation-delay:240ms]" />
    </span>
  );
}

function AttachmentView({ attachment }: { attachment: ChatAttachment }): ReactElement {
  switch (attachment.kind) {
    case "image":
      return (
        <figure className="mt-2">
          {attachment.url ? (
            <img
              src={attachment.url}
              alt={attachment.caption ?? attachment.name ?? "image"}
              loading="lazy"
              className="max-h-72 rounded-tg"
            />
          ) : null}
          {attachment.caption ? (
            <figcaption className="mt-1 text-xs text-tg-hint">{attachment.caption}</figcaption>
          ) : null}
        </figure>
      );
    case "video":
      return (
        <figure className="mt-2">
          {attachment.url ? (
            <video src={attachment.url} controls playsInline className="max-h-72 rounded-tg" />
          ) : null}
          {attachment.caption ? (
            <figcaption className="mt-1 text-xs text-tg-hint">{attachment.caption}</figcaption>
          ) : null}
        </figure>
      );
    case "document":
      return (
        <a
          href={attachment.url ?? "#"}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-2 rounded-tg bg-tg-bg/60 px-2 py-1 text-xs"
        >
          <span aria-hidden>📄</span>
          <span className="font-medium">{attachment.name ?? "document"}</span>
          {attachment.sizeBytes ? (
            <span className="text-tg-hint">{formatBytes(attachment.sizeBytes)}</span>
          ) : null}
        </a>
      );
    case "search_results":
      return <SearchResults attachment={attachment} />;
    default:
      return <></>;
  }
}

function SearchResults({ attachment }: { attachment: ChatAttachment }): ReactElement {
  const results = Array.isArray(attachment.data)
    ? (attachment.data as Array<{ title: string; url: string; snippet?: string | null }>)
    : [];
  if (results.length === 0) return <></>;
  return (
    <ul className="mt-2 space-y-1 text-xs">
      {results.map((r) => (
        <li key={r.url} className="border-l-2 border-tg-separator pl-2">
          <a
            href={r.url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-tg-link underline"
          >
            {r.title}
          </a>
          {r.snippet ? <p className="text-tg-hint">{r.snippet}</p> : null}
        </li>
      ))}
    </ul>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
