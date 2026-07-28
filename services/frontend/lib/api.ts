import type { ChatMessage } from "./types";

export interface ChatResponse {
  response: string;
  prediction_id?: string | null;
  annotated_image?: string | null;
  annotated_image_url?: string | null;
  agent_loop_time_s: number;
  iterations: number;
  tools_called: string[];
  context_limit_exceeded: boolean;
  tokens_used: {
    input: number;
    output: number;
    total: number;
  };
}

export async function sendMessage(messages: ChatMessage[]): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || res.statusText);
  }

  const data = await res.json() as ChatResponse;

  if (data.annotated_image_url) {
    const separator = data.annotated_image_url.includes("?") ? "&" : "?";
    data.annotated_image_url =
      `${data.annotated_image_url}${separator}v=${Date.now()}`;
  }

  return data;
}
