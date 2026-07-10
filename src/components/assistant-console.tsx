"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import { Tool, ToolHeader } from "@/components/ai-elements/tool";
import {
  ArrowUpIcon,
  CopyIcon,
  LogOutIcon,
  MonitorCogIcon,
  RotateCcwIcon,
  SquareIcon,
  UnplugIcon,
} from "lucide-react";

type AgentStatus = "offline" | "connecting" | "idle" | "thinking" | "working";
type ChatMessage = { id: string; role: "user" | "assistant"; text: string };
type ToolState = "input-available" | "output-available" | "output-error";
type ToolRun = { id: string; name: string; state: ToolState };
type BridgeConfig = { url: string; token: string };

const makeId = () => crypto.randomUUID();

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

export function AssistantConsole() {
  const router = useRouter();
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const streamingRef = useRef("");
  const [status, setStatus] = useState<AgentStatus>("connecting");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tools, setTools] = useState<ToolRun[]>([]);
  const [streaming, setStreaming] = useState("");
  const [input, setInput] = useState("");
  const [bridgeError, setBridgeError] = useState("");

  useEffect(() => {
    mountedRef.current = true;

    async function connect() {
      if (!mountedRef.current) return;
      setStatus("connecting");

      try {
        const configResponse = await fetch("/api/bridge-config", { cache: "no-store" });
        if (configResponse.status === 401) {
          router.replace("/sign-in");
          return;
        }
        if (!configResponse.ok) throw new Error("The local bridge is not configured.");
        const config = (await configResponse.json()) as BridgeConfig;
        const socket = new WebSocket(config.url);
        socketRef.current = socket;

        socket.onopen = () => {
          socket.send(JSON.stringify({ type: "authenticate", token: config.token }));
        };

        socket.onmessage = (event) => {
          let data: Record<string, unknown> | null = null;
          try {
            data = asRecord(JSON.parse(String(event.data)));
          } catch {
            setBridgeError("The local bridge sent an invalid event.");
          }
          if (!data || typeof data.type !== "string") return;

          if (data.type === "auth_ok") {
            setStatus("idle");
            setBridgeError("");
          } else if (data.type === "auth_error") {
            setBridgeError("The local bridge rejected this web session.");
            socket.close();
          } else if (data.type === "status") {
            const value = data.value;
            if (value === "thinking") setStatus("thinking");
            else if (value === "working") setStatus("working");
            else if (value === "idle") setStatus("idle");
          } else if (data.type === "stream_start") {
            streamingRef.current = "";
            setStreaming("");
          } else if (data.type === "stream_delta" && typeof data.text === "string") {
            streamingRef.current += data.text;
            setStreaming(streamingRef.current);
          } else if (data.type === "stream_end") {
            const text = typeof data.text === "string" ? data.text : streamingRef.current;
            if (text) {
              setMessages((current) => [...current, { id: makeId(), role: "assistant", text }]);
            }
            streamingRef.current = "";
            setStreaming("");
            setTools((current) => current.map((tool) => ({ ...tool, state: "output-available" })));
            setStatus("idle");
          } else if (data.type === "stream_cancel") {
            streamingRef.current = "";
            setStreaming("");
            setStatus("idle");
          } else if (data.type === "message" && typeof data.text === "string") {
            setMessages((current) => [
              ...current,
              { id: makeId(), role: "assistant", text: data.text as string },
            ]);
          } else if (data.type === "tool" && typeof data.name === "string") {
            setStatus("working");
            setTools((current) => [
              ...current,
              { id: makeId(), name: data.name as string, state: "input-available" },
            ]);
          } else if (data.type === "tool_error" && typeof data.name === "string") {
            setTools((current) =>
              current.map((tool) =>
                tool.name === data.name ? { ...tool, state: "output-error" } : tool,
              ),
            );
          } else if (data.type === "session_reset") {
            setMessages([]);
            setTools([]);
            setStreaming("");
          } else if (data.type === "error" && typeof data.message === "string") {
            setBridgeError(data.message);
            setStatus("idle");
          }
        };

        socket.onerror = () => setBridgeError("Could not reach the agent running on this Mac.");
        socket.onclose = () => {
          socketRef.current = null;
          if (!mountedRef.current) return;
          setStatus("offline");
          reconnectRef.current = setTimeout(connect, 3000);
        };
      } catch (error) {
        setStatus("offline");
        setBridgeError(error instanceof Error ? error.message : "Could not connect to Cortana.");
        reconnectRef.current = setTimeout(connect, 3000);
      }
    }

    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      socketRef.current?.close();
    };
  }, [router]);

  function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = input.trim();
    if (
      !text ||
      status === "offline" ||
      status === "connecting" ||
      status === "thinking" ||
      status === "working"
    ) return;
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;

    setMessages((current) => [...current, { id: makeId(), role: "user", text }]);
    setTools([]);
    setInput("");
    setStatus("thinking");
    socket.send(JSON.stringify({ type: "message", text }));
  }

  function stop() {
    socketRef.current?.send(JSON.stringify({ type: "stop" }));
  }

  function reset() {
    socketRef.current?.send(JSON.stringify({ type: "reset" }));
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/sign-in");
    router.refresh();
  }

  const busy = status === "thinking" || status === "working";

  return (
    <main className="agent-shell">
      <aside className="agent-rail">
        <div className="rail-brand">
          <div className="cortana-mark">C</div>
          <div>
            <strong>Cortana</strong>
            <span>Personal agent</span>
          </div>
        </div>

        <div className="rail-section">
          <p className="rail-label">Runtime</p>
          <div className="runtime-card">
            <div className={`status-light ${status}`} />
            <div>
              <strong>{status === "offline" ? "Bridge offline" : `Agent ${status}`}</strong>
              <span>GPT-5.5 · This Mac</span>
            </div>
          </div>
        </div>

        <div className="rail-section tool-section">
          <p className="rail-label">Current work</p>
          {tools.length ? (
            <div className="tool-list">
              {tools.map((tool) => (
                <Tool key={tool.id}>
                  <ToolHeader
                    type="dynamic-tool"
                    toolName={tool.name}
                    state={tool.state}
                    title={tool.name.replaceAll("_", " ")}
                  />
                </Tool>
              ))}
            </div>
          ) : (
            <p className="rail-empty">Tool calls will appear here while Cortana works.</p>
          )}
        </div>

        <div className="rail-actions">
          <button type="button" onClick={reset}><RotateCcwIcon /> New conversation</button>
          <button type="button" onClick={logout}><LogOutIcon /> Sign out</button>
        </div>
      </aside>

      <section className="agent-main">
        <header className="agent-header">
          <div>
            <p className="eyebrow">Authenticated command surface</p>
            <h1>What should I handle?</h1>
          </div>
          <div className={`connection-pill ${status}`}>
            {status === "offline" ? <UnplugIcon /> : <MonitorCogIcon />}
            {status}
          </div>
        </header>

        {bridgeError ? <div className="bridge-warning">{bridgeError}</div> : null}

        <Conversation className="conversation">
          <ConversationContent className="conversation-content">
            {messages.length === 0 && !streaming ? (
              <ConversationEmptyState
                icon={<MonitorCogIcon size={34} />}
                title="Your Mac, on command"
                description="Ask Cortana to research, organize files, manage apps, write code, or complete a multi-step task."
              />
            ) : null}

            {messages.map((message) => (
              <Message from={message.role} key={message.id}>
                <MessageContent>
                  <MessageResponse>{message.text}</MessageResponse>
                </MessageContent>
                {message.role === "assistant" ? (
                  <MessageActions>
                    <MessageAction
                      tooltip="Copy response"
                      onClick={() => navigator.clipboard.writeText(message.text)}
                    >
                      <CopyIcon className="size-3.5" />
                    </MessageAction>
                  </MessageActions>
                ) : null}
              </Message>
            ))}

            {streaming ? (
              <Message from="assistant">
                <MessageContent>
                  <MessageResponse parseIncompleteMarkdown>{streaming}</MessageResponse>
                </MessageContent>
              </Message>
            ) : null}

            {busy && !streaming ? (
              <div className="working-indicator"><span /><span /><span /> Cortana is working</div>
            ) : null}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>

        <div className="composer-wrap">
          <form className="composer" onSubmit={send}>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={status === "offline" ? "Start the local Cortana agent to continue" : "Ask Cortana to do something…"}
              rows={2}
              disabled={status === "offline" || status === "connecting"}
            />
            {busy ? (
              <button className="composer-action stop" type="button" onClick={stop} aria-label="Stop">
                <SquareIcon />
              </button>
            ) : (
              <button className="composer-action" type="submit" disabled={!input.trim()} aria-label="Send">
                <ArrowUpIcon />
              </button>
            )}
          </form>
          <p>Enter to send · Shift+Enter for a new line · Local actions run on this Mac</p>
        </div>
      </section>
    </main>
  );
}
