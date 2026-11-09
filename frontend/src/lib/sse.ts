/**
 * Fetch-based Server-Sent Events client (ADR-006).
 *
 * EventSource cannot send an Authorization header, so the bearer token would have to go in the
 * URL. This client streams with fetch instead, resumes with Last-Event-ID after a disconnect and
 * stops when the server sends `event: end`.
 */
import { fetchWithAuth } from "@/lib/api-client";

export interface SseMessage {
  id: string | null;
  event: string;
  data: string;
}

/** Parse complete SSE messages from a text buffer; returns the unconsumed remainder. */
export function parseSse(buffer: string): { messages: SseMessage[]; rest: string } {
  const messages: SseMessage[] = [];
  const blocks = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let id: string | null = null;
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "id") id = value;
      else if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length || id !== null) messages.push({ id, event, data: data.join("\n") });
  }
  return { messages, rest };
}

export interface StreamOptions {
  onMessage: (message: SseMessage) => void;
  onStateChange?: (state: "connecting" | "open" | "reconnecting" | "closed") => void;
  signal: AbortSignal;
  lastEventId?: string | null;
}

/** Stream until `event: end` or abort; reconnects (with backoff) on network drops. */
export async function streamEvents(path: string, options: StreamOptions): Promise<void> {
  const { onMessage, onStateChange, signal } = options;
  let lastEventId = options.lastEventId ?? null;
  let attempt = 0;
  onStateChange?.("connecting");
  while (!signal.aborted) {
    try {
      const response = await fetchWithAuth(path, {
        signal,
        headers: { Accept: "text/event-stream", ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}) },
      });
      if (!response.body) throw new Error("Streaming is not supported by this browser.");
      onStateChange?.("open");
      attempt = 0;
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const parsed = parseSse(buffer + value);
        buffer = parsed.rest;
        for (const message of parsed.messages) {
          if (message.id) lastEventId = message.id;
          if (message.event === "end") {
            onStateChange?.("closed");
            return;
          }
          onMessage(message);
        }
      }
    } catch (error) {
      if (signal.aborted) break;
      // Missing runs or permissions will not fix themselves: stop instead of retrying.
      if (error && typeof error === "object" && "status" in error) {
        const status = (error as { status: number }).status;
        if (status >= 400 && status < 500) {
          onStateChange?.("closed");
          throw error;
        }
      }
    }
    if (signal.aborted) break;
    // The server closes long streams on purpose; reconnect and resume after the last event.
    onStateChange?.("reconnecting");
    attempt += 1;
    await new Promise((resolve) => setTimeout(resolve, Math.min(1000 * attempt, 5000)));
  }
  onStateChange?.("closed");
}
