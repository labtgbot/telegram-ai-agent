import { describe, expect, it, vi } from "vitest";

import { estimateMessageCost, streamTextGeneration } from "@/services/chatApi";

const ENCODER = new TextEncoder();

function chunkedBody(frames: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(ENCODER.encode(frame));
      controller.close();
    },
  });
}

function jsonFrame(payload: object): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

describe("estimateMessageCost", () => {
  it("returns the mode price", () => {
    expect(estimateMessageCost("basic")).toBe(1);
    expect(estimateMessageCost("advanced")).toBe(5);
    expect(estimateMessageCost("autonomous_agent")).toBe(10);
  });
});

describe("streamTextGeneration", () => {
  it("dispatches start, delta and final SSE events", async () => {
    const body = chunkedBody([
      jsonFrame({ event: "start", requestId: "req-1" }),
      jsonFrame({ event: "delta", content: "Hello" }),
      jsonFrame({ event: "delta", content: " world" }),
      jsonFrame({
        event: "final",
        text: "Hello world",
        tokens_spent: 1,
        new_balance: 99,
        mode: "basic",
        request_id: "req-1",
        thread_id: "t-1",
      }),
      jsonFrame({ event: "done" }),
    ]);

    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(body, { status: 200 }));

    const onStart = vi.fn();
    const onDelta = vi.fn();
    const onFinal = vi.fn();
    const onError = vi.fn();

    await streamTextGeneration(
      { prompt: "hi", mode: "basic", threadId: "t-1" },
      { onStart, onDelta, onFinal, onError },
      fetchImpl as unknown as typeof fetch,
    );

    expect(onStart).toHaveBeenCalledWith("req-1");
    expect(onDelta).toHaveBeenNthCalledWith(1, "Hello");
    expect(onDelta).toHaveBeenNthCalledWith(2, " world");
    expect(onFinal).toHaveBeenCalledTimes(1);
    expect(onFinal.mock.calls[0]?.[0]).toMatchObject({
      tokens_spent: 1,
      mode: "basic",
    });
    expect(onError).not.toHaveBeenCalled();
    expect(fetchImpl).toHaveBeenCalledWith(
      expect.stringContaining("/generate/text/stream"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("calls onError when the HTTP status is not OK", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "boom" }), {
          status: 402,
          headers: { "content-type": "application/json" },
        }),
      );
    const onError = vi.fn();

    await streamTextGeneration(
      { prompt: "x", mode: "basic", threadId: "t" },
      { onError },
      fetchImpl as unknown as typeof fetch,
    );

    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ error: "http_402" }),
    );
  });

  it("propagates an error event from the stream", async () => {
    const body = chunkedBody([
      jsonFrame({ event: "start", requestId: "r" }),
      jsonFrame({ event: "error", error: "stream_failed", message: "nope" }),
      jsonFrame({ event: "done" }),
    ]);
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(body, { status: 200 }));
    const onError = vi.fn();
    await streamTextGeneration(
      { prompt: "x", mode: "basic", threadId: "t" },
      { onError },
      fetchImpl as unknown as typeof fetch,
    );
    expect(onError).toHaveBeenCalledWith({
      error: "stream_failed",
      message: "nope",
    });
  });
});
