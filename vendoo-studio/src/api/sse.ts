/** Read a `text/event-stream` response, calling `onEvent` once per complete event. */
export async function readSse(
  res: Response,
  onEvent: (event: string, data: string) => void,
): Promise<void> {
  const reader = res.body?.getReader();
  if (!reader) {
    dispatch(await res.text(), onEvent);
    return;
  }
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) dispatch(block, onEvent);
  }
  if (buffer.trim()) dispatch(buffer, onEvent);
}

function dispatch(text: string, onEvent: (event: string, data: string) => void): void {
  for (const block of text.split("\n\n")) {
    let event = "message";
    const data: string[] = [];
    for (const raw of block.split("\n")) {
      const line = raw.replace(/\r$/, "");
      if (line.startsWith("event:")) event = line.slice(6).trim() || "message";
      else if (line.startsWith("data:")) data.push(line.startsWith("data: ") ? line.slice(6) : line.slice(5));
    }
    if (!data.length) continue;
    const joined = data.join("\n");
    if (joined === "[DONE]") continue;
    onEvent(event, joined);
  }
}
