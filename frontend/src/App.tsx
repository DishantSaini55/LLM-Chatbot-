import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Metadata, getHealth, getHistory, sendChat } from "./api";
import { Icon } from "./Icon";

type Message = { id: string; role: "user" | "assistant" | "error"; content: string; metadata?: Metadata; retryText?: string };
type SavedChat = { id: string; title: string; updatedAt: string };
const HISTORY_KEY = "lyftr.conversations.v1";
const starters = [
  { icon: "code" as const, title: "Build something", description: "Turn an idea into a plan", prompt: "Help me plan a small web app. Ask me about my idea first." },
  { icon: "sparkles" as const, title: "Make it clear", description: "Understand a complex topic", prompt: "Explain how AI chatbots remember conversations, using a simple example." },
  { icon: "edit" as const, title: "Find the right words", description: "Write with a little more impact", prompt: "Help me write a professional introduction. Ask me what it is for first." },
];

function readChats(): SavedChat[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item): item is SavedChat => typeof item?.id === "string" && typeof item?.title === "string" && typeof item?.updatedAt === "string").slice(0, 30) : [];
  } catch { return []; }
}
function readTheme(): "light" | "dark" {
  try { return localStorage.getItem("lyftr.theme") === "dark" ? "dark" : "light"; }
  catch { return "light"; }
}

function ResponseDetails({ metadata }: { metadata: Metadata }) {
  const cached = metadata.resolution_source === "LLM_CACHE";
  return <div className="response-details">
    <span className={`source-tag ${cached ? "cached" : "live"}`} data-testid="meta-source"><Icon name={cached ? "bolt" : "pulse"} size={12} />{metadata.resolution_source}</span>
    <span className="latency" data-testid="meta-latency"><Icon name="clock" size={12} />{metadata.latency_ms} ms</span>
    <span className="model-name" data-testid="meta-model" title={metadata.model}>{metadata.model}</span>
    <span className="token-breakdown" aria-label="Per-request token usage"><span data-testid="meta-input-tokens">{metadata.input_tokens}</span> in <span className="token-divider">/</span> <span data-testid="meta-output-tokens">{metadata.output_tokens}</span> out</span>
    <details className="request-details"><summary>Routing details <Icon name="chevron" size={12} /></summary><dl>
      <div><dt>Answering key</dt><dd>{metadata.key_id ?? "None · cached response"}</dd></div>
      <div><dt>Fallback attempts</dt><dd>{metadata.fallback_attempts}</dd></div>
    </dl></details>
  </div>;
}

export default function App() {
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID());
  const [message, setMessage] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [instructionsEdited, setInstructionsEdited] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [savedChats, setSavedChats] = useState<SavedChat[]>(readChats);
  const [search, setSearch] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [simulatedFailure, setSimulatedFailure] = useState("");
  const [theme, setTheme] = useState(readTheme);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [copiedId, setCopiedId] = useState("");
  const [health, setHealth] = useState<"checking" | "online" | "offline">("checking");
  const busyRef = useRef(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const settings = useRef<HTMLDialogElement>(null);
  const busy = isSending || isLoading;
  const answers = messages.filter((item) => item.role === "assistant" && item.metadata);
  const cacheHits = answers.filter((item) => item.metadata?.resolution_source === "LLM_CACHE").length;
  const title = messages.find((item) => item.role === "user")?.content ?? "New conversation";
  const lastAnswer = answers[answers.length - 1];

  useEffect(() => {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(savedChats)); } catch { /* Optional browser storage. */ }
  }, [savedChats]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("lyftr.theme", theme); } catch { /* Optional preference. */ }
  }, [theme]);
  useEffect(() => {
    const controller = new AbortController();
    const check = async () => {
      try { await getHealth(controller.signal); if (!controller.signal.aborted) setHealth("online"); }
      catch { if (!controller.signal.aborted) setHealth("offline"); }
    };
    void check();
    const timer = window.setInterval(check, 30000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, isSending]);
  useEffect(() => {
    if (textarea.current) {
      textarea.current.style.height = "auto";
      textarea.current.style.height = `${Math.min(textarea.current.scrollHeight, 160)}px`;
    }
  }, [message]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3000);
    return () => window.clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!copiedId) return;
    const timer = window.setTimeout(() => setCopiedId(""), 2000);
    return () => window.clearTimeout(timer);
  }, [copiedId]);

  function startNewChat() {
    if (busyRef.current) return;
    setSessionId(crypto.randomUUID()); setMessages([]); setMessage("");
    setSystemPrompt(""); setInstructionsEdited(false); setSimulatedFailure(""); setSidebarOpen(false);
    textarea.current?.focus();
  }
  async function loadChat(chat: SavedChat) {
    if (busyRef.current) return;
    busyRef.current = true; setIsLoading(true); setSidebarOpen(false);
    try {
      const history = await getHistory(chat.id);
      setSessionId(chat.id);
      setMessages(history.messages.map((item) => ({ ...item, id: crypto.randomUUID() })));
      setMessage(""); setSystemPrompt(""); setInstructionsEdited(false); setSimulatedFailure("");
    } catch (error) { setToast(error instanceof Error ? error.message : "Could not open conversation."); }
    finally { busyRef.current = false; setIsLoading(false); }
  }
  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const text = message.trim();
    if (!text || text.length > 4000 || busyRef.current) return;
    busyRef.current = true;
    const failure = simulatedFailure;
    // Demo failures apply once, so ordinary follow-up messages work normally.
    setSimulatedFailure("");
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: "user", content: text }]);
    setMessage(""); setIsSending(true);
    try {
      const response = await sendChat(sessionId, text, instructionsEdited ? systemPrompt : undefined, failure);
      setMessages((current) => [...current, { id: crypto.randomUUID(), role: "assistant", content: response.reply, metadata: response.metadata }]);
      setSavedChats((current) => [{ id: sessionId, title: (title === "New conversation" ? text : title).slice(0, 70), updatedAt: new Date().toISOString() }, ...current.filter((chat) => chat.id !== sessionId)].slice(0, 30));
    } catch (error) {
      setMessages((current) => [...current, { id: crypto.randomUUID(), role: "error", content: error instanceof Error ? error.message : "Unable to send this message.", retryText: text }]);
    } finally { busyRef.current = false; setIsSending(false); textarea.current?.focus(); }
  }
  function onMessageKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); }
  }
  async function copyReply(item: Message) {
    try { await navigator.clipboard.writeText(item.content); setCopiedId(item.id); }
    catch { setToast("Clipboard unavailable. You can select and copy the reply text."); }
  }
  function exportChat() {
    const text = [`# ${title}`, "", ...messages.flatMap((item) => [`## ${item.role === "user" ? "You" : item.role === "assistant" ? "Lyftr" : "Request error"}`, "", item.content, "", ...(item.metadata ? [`Source: ${item.metadata.resolution_source} | Model: ${item.metadata.model} | Latency: ${item.metadata.latency_ms} ms | Input tokens: ${item.metadata.input_tokens} | Output tokens: ${item.metadata.output_tokens}`, ""] : [])])].join("\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `lyftr-chat-${sessionId.slice(0, 8)}.md`;
    link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); setToast("Conversation exported.");
  }

  return <div className={`app-layout ${sidebarOpen ? "sidebar-open" : ""}`}>
    {sidebarOpen && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} />}
    <aside className="sidebar" aria-label="Conversations">
      <a className="brand" href="#" onClick={(event) => { event.preventDefault(); startNewChat(); }} aria-label="Lyftr home"><span className="brand-symbol"><Icon name="layers" size={23} /></span><span>lyftr<span className="brand-period">.</span></span><span className="brand-label">WORKSPACE</span></a>
      <button className="new-chat" onClick={startNewChat} disabled={busy}><Icon name="plus" size={18} />New conversation<span className="new-chat-arrow"><Icon name="arrow" size={16} /></span></button>
      <div className="history-heading"><span>YOUR CONVERSATIONS</span><span>{savedChats.length}</span></div>
      <label className="history-search"><Icon name="search" size={16} /><input aria-label="Search conversations" placeholder="Search conversations" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <nav className="history-list" aria-label="Saved conversations">
        {savedChats.filter((chat) => chat.title.toLowerCase().includes(search.toLowerCase())).map((chat) => <button key={chat.id} className={`history-item ${chat.id === sessionId ? "active" : ""}`} disabled={busy} onClick={() => void loadChat(chat)}><Icon name="chat" size={16} /><span>{chat.title}</span>{chat.id === sessionId && <span className="active-dot" />}</button>)}
        {savedChats.length === 0 && <div className="history-empty"><Icon name="chat" size={22} /><p>A little space for your big ideas.</p><span>Your conversations will appear here.</span></div>}
        {savedChats.length > 0 && !savedChats.some((chat) => chat.title.toLowerCase().includes(search.toLowerCase())) && <p className="search-empty">No conversations found.</p>}
      </nav>
      <div className="sidebar-bottom">
        <div className="session-summary"><div className="summary-title"><Icon name="pulse" size={15} /><span>This conversation</span></div><div className="summary-stats"><span><strong>{answers.length}</strong> replies</span><span><strong>{cacheHits}</strong> cache hits</span></div></div>
        <button className="sidebar-settings" onClick={() => settings.current?.showModal()}><Icon name="settings" size={17} />Conversation settings<Icon name="chevron" size={14} /></button>
        <div className="workspace-account"><span className="account-avatar">Y</span><div><strong>Your workspace</strong><span>History saved on this device</span></div><span className="account-status" /></div>
      </div>
    </aside>
    <main className="workspace">
      <header className="topbar">
        <div className="topbar-left"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setSidebarOpen(true)}><Icon name="menu" /></button><span className="breadcrumb">Workspace</span><Icon name="chevron" size={13} /><span className="conversation-title">{title}</span></div>
        <div className="topbar-actions"><span className={`connection-status ${health}`} title="Backend health is checked every 30 seconds. Provider availability may vary."><span />{health === "online" ? "Backend online" : health === "offline" ? "Backend offline" : "Connecting"}</span><span className="topbar-divider" /><button className="icon-button" aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`} onClick={() => setTheme(theme === "light" ? "dark" : "light")}><Icon name={theme === "light" ? "moon" : "sun"} size={18} /></button><button className="icon-button" aria-label="Export conversation" disabled={!messages.length || busy} onClick={exportChat}><Icon name="download" size={18} /></button></div>
      </header>
      <section className={`conversation ${messages.length ? "has-messages" : ""}`} aria-label="Conversation" aria-busy={isLoading}>
        {isLoading ? <div className="loading-history"><span className="spinner" />Opening your conversation...</div> : !messages.length ? <div className="welcome">
          <span className="welcome-label"><span />A little clarity. A lot of possibility.</span>
          <div className="welcome-emblem"><Icon name="sparkles" size={35} /></div>
          <h1>Good ideas start<br />with a <span>conversation.</span></h1>
          <p>Your space to think, create, and figure things out.<br className="desktop-break" />Bring a question. We’ll take it from there.</p>
          <div className="starter-grid">{starters.map((starter) => <button className="starter-card" key={starter.title} onClick={() => { setMessage(starter.prompt); textarea.current?.focus(); }}><span className="starter-icon"><Icon name={starter.icon} size={19} /></span><strong>{starter.title}</strong><span>{starter.description}</span><Icon name="arrow" size={16} /></button>)}</div>
          <div className="welcome-note"><Icon name="shield" size={14} /><span>Conversation memory. Faster repeat answers. Automatic backup.</span></div>
        </div> : <div className="message-list" aria-live="polite">
          <div className="conversation-date"><span />Your conversation<span /></div>
          {messages.map((item) => <article key={item.id} className={`message ${item.role}`} {...(item.role === "assistant" ? { "data-testid": "assistant-message" } : {})}>
            <span className={`message-avatar ${item.role}`}><Icon name={item.role === "user" ? "user" : item.role === "error" ? "alert" : "layers"} size={18} /></span>
            <div className="message-body"><div className="message-heading"><strong>{item.role === "user" ? "You" : item.role === "assistant" ? "Lyftr" : "Couldn’t send this message"}</strong>{item.role === "assistant" && <span className="ai-label">AI</span>}{item.role === "assistant" && <button className={`copy-button ${copiedId === item.id ? "copied" : ""}`} aria-label={copiedId === item.id ? "Reply copied" : "Copy reply"} onClick={() => void copyReply(item)}><Icon name={copiedId === item.id ? "check" : "copy"} size={14} /><span>{copiedId === item.id ? "Copied" : "Copy"}</span></button>}</div>
              {item.role === "assistant" ? <div className="markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>, img: ({ alt }) => <span>[Image: {alt ?? "image"}]</span> }}>{item.content}</Markdown></div> : <p className="message-text">{item.content}</p>}
              {item.metadata && <ResponseDetails metadata={item.metadata} />}
              {item.role === "error" && <div className="error-recovery"><p>Your message wasn’t saved to the conversation. You can edit it and try again.</p><button onClick={() => { setMessage(item.retryText ?? ""); textarea.current?.focus(); }}><Icon name="retry" size={14} />Edit & retry</button></div>}
            </div>
          </article>)}
          {isSending && <div className="message pending" role="status"><span className="message-avatar assistant"><Icon name="layers" size={18} /></span><div className="message-body"><div className="message-heading"><strong>Lyftr</strong><span className="ai-label">AI</span></div><div className="thinking"><span /><span /><span /><span className="thinking-label">Thinking it through</span></div></div></div>}
        </div>}
        <div ref={bottom} />
      </section>
      <div className="composer-area">
        {simulatedFailure && <div className="simulation-banner"><Icon name="alert" size={15} /><span>Failure simulation is on for your next message.</span><button aria-label="Cancel failure simulation" onClick={() => setSimulatedFailure("")}><Icon name="close" size={15} /></button></div>}
        <form className={`composer ${message.trim().length > 4000 ? "invalid" : ""}`} onSubmit={submit}>
          <label htmlFor="chat-input">Your message</label>
          <textarea ref={textarea} id="chat-input" data-testid="chat-input" value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={onMessageKeyDown} placeholder="Ask Lyftr anything..." rows={2} disabled={isLoading} aria-describedby="composer-help" />
          <div className="composer-toolbar"><div className="composer-options"><span className="model-chip"><Icon name="sparkles" size={13} />{lastAnswer?.metadata?.model.replace("gemini/", "") ?? "Auto-configured model"}</span><button type="button" className="composer-settings" onClick={() => settings.current?.showModal()} aria-label="Open conversation settings"><Icon name="sliders" size={15} /><span>Customize</span>{systemPrompt && <i />}</button></div><div className="send-actions">{message.length > 3500 && <span className={`character-count ${message.trim().length > 4000 ? "over-limit" : ""}`}>{message.trim().length}/4000</span>}<button data-testid="send-button" className="send-button" type="submit" aria-label="Send message" disabled={busy || !message.trim() || message.trim().length > 4000}><span>{isSending ? "Sending" : "Send"}</span><Icon name={isSending ? "clock" : "arrowUp"} size={17} /></button></div></div>
        </form>
        <div className="composer-footer" id="composer-help"><span><kbd>Enter</kbd> to send<span className="footer-separator">·</span><kbd>Shift + Enter</kbd> for a new line</span><span>AI can make mistakes. Review important details.</span></div>
      </div>
    </main>
    <dialog className="settings-dialog" ref={settings} aria-labelledby="settings-title">
      <div className="dialog-heading"><span className="dialog-icon"><Icon name="sliders" size={21} /></span><button className="icon-button" aria-label="Close settings" onClick={() => settings.current?.close()}><Icon name="close" size={20} /></button></div>
      <h2 id="settings-title">Make it your own.</h2><p className="dialog-description">Set the tone for this conversation.</p>
      <label htmlFor="system-prompt">Assistant instructions<span>Optional</span></label><p className="field-description">Tell Lyftr how to respond. Type your questions in the main message box.</p>
      <textarea id="system-prompt" data-testid="system-prompt-input" value={systemPrompt} disabled={busy} onChange={(event) => { setSystemPrompt(event.target.value); setInstructionsEdited(true); }} maxLength={4000} placeholder="For example: Explain concepts simply and include a practical example." rows={4} />
      <button className="reset-instructions" disabled={busy} onClick={() => { setSystemPrompt(""); setInstructionsEdited(true); }}><Icon name="retry" size={12} />Use default instructions</button>
      <div className="preset-list">{["Be concise and direct.", "Explain step by step with examples.", "Act as a thoughtful writing partner."].map((preset) => <button key={preset} disabled={busy} onClick={() => { setSystemPrompt(preset); setInstructionsEdited(true); }}>{preset}<Icon name="plus" size={13} /></button>)}</div>
      <details className="advanced-settings"><summary><Icon name="shield" size={16} />Developer tools<Icon name="chevron" size={14} /></summary><label htmlFor="failure-mode">Test provider failover</label><select id="failure-mode" value={simulatedFailure} disabled={busy} onChange={(event) => setSimulatedFailure(event.target.value)}><option value="">Normal request</option><option value="key_1=429">First key rate-limited (429)</option><option value="key_1=500">First key unavailable (500)</option><option value="*=429">All keys rate-limited</option></select><p>Applies to your next message only, then resets. Simulation bypasses cache and requires server support. Successful fallback uses a real backup key.</p></details>
      <button className="dialog-done" onClick={() => settings.current?.close()}>Done<Icon name="check" size={16} /></button>
    </dialog>
    {toast && <div className="toast" role="status"><Icon name="chat" size={16} />{toast}<button aria-label="Dismiss notification" onClick={() => setToast("")}><Icon name="close" size={14} /></button></div>}
  </div>;
}
