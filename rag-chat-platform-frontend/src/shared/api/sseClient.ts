export type SSEEvent =
  | { event: "token"; data: { delta: string } }
  | { event: "final"; data: { content?: string } }
  | { event: "trace"; data: unknown }
  | { event: "verification"; data: unknown }
  | { event: "error"; data: { message: string } }
  | { event: string; data: unknown };

type SSEHandler = (evt: SSEEvent) => void;

export async function postSSE(url: string, body: unknown, onEvent: SSEHandler, signal?: AbortSignal) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) throw new Error(`SSE failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });

    const chunks = buf.split("\n\n");
    buf = chunks.pop() ?? "";

    for (const chunk of chunks) {
      const lines = chunk.split("\n");
      let event = "message";
      let dataStr = "";

      for (const line of lines) {
        if (line.startsWith("event:")) event = line.replace("event:", "").trim();
        if (line.startsWith("data:")) dataStr += line.replace("data:", "").trim();
      }

      if (dataStr) {
        const data: unknown = JSON.parse(dataStr);
        onEvent({ event, data } as SSEEvent);
      }
    }
  }
}
