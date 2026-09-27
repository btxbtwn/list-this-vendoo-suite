import { describe, expect, it } from "vitest";
import { readSse } from "./sse";

function streamed(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body);
}

describe("readSse", () => {
  it("joins events split across chunks and multi-line data", async () => {
    const events: [string, string][] = [];
    await readSse(
      streamed([
        'event: source\ndata: {"source":"Cur',
        'sor"}\n\n: keepalive\n\nevent: step\ndata: one\ndata: two\n\n',
        "data: [DONE]\n\n",
      ]),
      (event, data) => events.push([event, data]),
    );
    expect(events).toEqual([
      ["source", '{"source":"Cursor"}'],
      ["step", "one\ntwo"],
    ]);
  });
});
