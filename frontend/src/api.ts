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

export async function getHealth(signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${baseUrl}/health`, { signal });
  if (!response.ok) throw new Error("Backend is unavailable.");
  if ((await response.json()).status !== "ok") throw new Error("Backend is not ready.");
}

export async function getHistory(sessionId: string): Promise<{
  messages: { role: "user" | "assistant"; content: string; metadata?: Metadata }[];
}> {
  const response = await fetch(`${baseUrl}/sessions/${encodeURIComponent(sessionId)}/messages`);
  if (!response.ok) throw new Error(response.status === 404 ? "This conversation is no longer available on the server." : "Could not load conversation. Please try again.");
  return response.json();
}

export async function sendChat(
  sessionId: string,
  message: string,
  systemPrompt: string | undefined,
  simulatedFailure = "",
): Promise<ChatResponse> {
  const response = await fetch(`${baseUrl}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(simulatedFailure ? { "X-Simulate-Failure": simulatedFailure } : {}),
    },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      ...(systemPrompt !== undefined ? { system_prompt: systemPrompt.trim() } : {}),
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
