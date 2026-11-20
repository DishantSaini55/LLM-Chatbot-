import { FormEvent, KeyboardEvent, useRef, useState } from "react";
import { Metadata, sendChat } from "./api";

type ChatMessage =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; content: string; metadata: Metadata }
  | { id: string; role: "error"; content: string };

function createSessionId(): string {
  // A page load deliberately starts a fresh session, as the brief requires.
  return crypto.randomUUID();
}

function AssistantMetadata({ metadata }: { metadata: Metadata }) {
  return (
    <dl className="metadata" aria-label="Response metadata">
      <div>
        <dt>Source</dt>
        <dd data-testid="meta-source">{metadata.resolution_source}</dd>
      </div>
      <div>
        <dt>Model</dt>
        <dd data-testid="meta-model">{metadata.model}</dd>
      </div>
      <div>
        <dt>Latency</dt>
        <dd data-testid="meta-latency">{metadata.latency_ms} ms</dd>
      </div>
      <div>
        <dt>Input tokens</dt>
        <dd data-testid="meta-input-tokens">{metadata.input_tokens}</dd>
      </div>
      <div>
        <dt>Output tokens</dt>
        <dd data-testid="meta-output-tokens">{metadata.output_tokens}</dd>
      </div>
      <div><dt>Answering key</dt><dd>{metadata.key_id ?? "No key (cached)"}</dd></div>
      <div><dt>Failed keys</dt><dd>{metadata.fallback_attempts}</dd></div>
    </dl>
  );
}

export default function App() {
  const sessionId = useRef(createSessionId()).current;
  const [message, setMessage] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [simulatedFailure, setSimulatedFailure] = useState("");

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const submittedMessage = message.trim();
    if (!submittedMessage || isSending) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: submittedMessage,
    };
    setMessages((current) => [...current, userMessage]);
    setMessage(""); // Required: clear the chat input once it is sent.
    setIsSending(true);

    try {
      const response = await sendChat(sessionId, submittedMessage, systemPrompt, simulatedFailure);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.reply,
          metadata: response.metadata,
        },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "error",
          content: error instanceof Error ? error.message : "Unable to send this message.",
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  function onMessageKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <main className="shell">
      <header>
        <p className="eyebrow">Resilient AI assistant</p>
        <h1>Lyftr Chat</h1>
        <p className="subtitle">Multi-turn chat with automatic key failover and response caching.</p>
      </header>

      <section className="chat" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 ? (
          <p className="empty-state">Ask a question to start this session.</p>
        ) : (
          messages.map((item) => (
            <article
              className={`message ${item.role}`}
              key={item.id}
              {...(item.role === "assistant" ? { "data-testid": "assistant-message" } : {})}
            >
              <p className="message-role">
                {item.role === "assistant" ? "Assistant" : item.role === "user" ? "You" : "Request error"}
              </p>
              <p className="message-content">{item.content}</p>
              {item.role === "assistant" && <AssistantMetadata metadata={item.metadata} />}
            </article>
          ))
        )}
      </section>

      <form className="composer" onSubmit={submit}>
        <details className="demo-controls">
          <summary>Test failover</summary>
          <label htmlFor="failure-mode">Simulate a provider failure</label>
          <select id="failure-mode" value={simulatedFailure} disabled={isSending} onChange={(event) => setSimulatedFailure(event.target.value)}>
            <option value="">Normal request</option>
            <option value="key_1=429">First key rate-limited (429)</option>
            <option value="key_1=500">First key unavailable (500)</option>
            <option value="*=429">All keys rate-limited</option>
          </select>
          <p>Simulation requires server support. Test requests bypass the cache; a successful fallback still needs a valid backup key.</p>
        </details>
        <label htmlFor="system-prompt">System prompt <span>(optional)</span></label>
        <input
          id="system-prompt"
          data-testid="system-prompt-input"
          value={systemPrompt}
          onChange={(event) => setSystemPrompt(event.target.value)}
          placeholder="e.g. Explain concepts with examples."
        />
        <label htmlFor="chat-input">Your message</label>
        <textarea
          id="chat-input"
          data-testid="chat-input"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={onMessageKeyDown}
          placeholder="Ask anything…"
          rows={3}
          disabled={isSending}
        />
        <button data-testid="send-button" type="submit" disabled={isSending || !message.trim()}>
          {isSending ? "Thinking…" : "Send"}
        </button>
      </form>
    </main>
  );
}
