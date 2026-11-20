export type Metadata = {
  resolution_source: "LIVE_INFERENCE" | "LLM_CACHE";
  model: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  key_id: string | null;
  fallback_attempts: number;
};

export type ChatResponse = {
  session_id: string;
  reply: string;
  metadata: Metadata;
};

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export async function sendChat(
  sessionId: string,
  message: string,
  systemPrompt: string,
): Promise<ChatResponse> {
  const response = await fetch(`${baseUrl}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      ...(systemPrompt.trim() ? { system_prompt: systemPrompt.trim() } : {}),
    }),
  });

  const body = (await response.json().catch(() => null)) as
    | ChatResponse
    | { detail?: unknown }
    | null;
  if (!response.ok) {
    const detail = body && "detail" in body ? body.detail : null;
    const explanation = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => item.msg ?? "Invalid input").join("; ")
        : "Unable to complete your request. Please try again.";
    throw new Error(explanation);
  }
  return body as ChatResponse;
}
