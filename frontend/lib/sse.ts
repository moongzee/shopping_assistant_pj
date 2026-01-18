export type SseMessage = {
  id?: string;
  event?: string;
  data?: any;
};

// POST + text/event-stream 응답을 직접 파싱하기 위한 간단 SSE 파서
export async function* parseSseStream(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    // 일부 서버/프록시는 CRLF(\r\n)로 라인을 구분합니다. 파싱 단순화를 위해 LF로 정규화합니다.
    if (buf.includes("\r\n")) buf = buf.replace(/\r\n/g, "\n");

    // SSE 프레임은 빈 줄(\n\n)로 구분
    while (true) {
      const idx = buf.indexOf("\n\n");
      if (idx === -1) break;
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);

      const lines = raw.split("\n").map((l) => l.trimEnd());
      let id: string | undefined;
      let event: string | undefined;
      const dataLines: string[] = [];

      for (const line of lines) {
        if (!line) continue;
        if (line.startsWith("id:")) id = line.slice(3).trim();
        else if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }

      let data: any = undefined;
      if (dataLines.length) {
        const joined = dataLines.join("\n");
        try {
          data = JSON.parse(joined);
        } catch {
          data = joined;
        }
      }

      yield { id, event, data };
    }
  }
}

