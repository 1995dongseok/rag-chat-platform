import { useMemo, useState } from "react";
import { useEffect, useRef } from "react";

type Conversation = { id: string; title: string; updatedAt: string };
type Message = { id: string; role: "user" | "assistant"; content: string; createdAt: string };

export default function ChatLayout() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60_000); // 1분마다 갱신
    return () => clearInterval(t);
  }, []);

  function formatNow(d: Date) {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
  }

  const [conversations] = useState<Conversation[]>(
  Array.from({ length: 50 }, (_, i) => ({
    id: `c${i + 1}`,
    title: `테스트 대화 ${i + 1}`,
    updatedAt: `2026-02-03 ${String(10 + (i % 10)).padStart(2, "0")}:${String(i % 60).padStart(2, "0")}`,
  }))
);

  const [activeConversationId, setActiveConversationId] = useState(conversations[0]?.id ?? "");
  const [messages, setMessages] = useState<Message[]>(
    Array.from({ length: 30 }, (_, i) => ({
      id: `m${i + 1}`,
      role: i % 2 === 0 ? "user" : "assistant",
      content: `테스트 메시지 ${i + 1}`,
      createdAt: "now",
    }))
  );

  const activeTitle = useMemo(
    () => conversations.find((c) => c.id === activeConversationId)?.title ?? "New Chat",
    [activeConversationId, conversations]
  );

  function onNewChat() {
    setMessages([]);
  }

  function onSend(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;

    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: trimmed, createdAt: "now" },
    ]);

    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "✅ (데모) 서버 연결 전입니다. 나중에 RAG 응답(SSE)로 교체하세요.",
          createdAt: "now",
        },
      ]);
    }, 250);
  }

  return (
    <div className="h-screen overflow-hidden grid grid-cols-[320px_1fr] bg-white text-slate-900">
      {/* Sidebar */}
      <aside className="min-h-0 border-r border-slate-200 bg-slate-50 p-4 flex flex-col gap-3">
        <div className="pb-1">
          <div className="font-bold">rag-chat-platform</div>
          <div className="text-xs text-slate-400">{formatNow(now)}</div>
        </div>

        <button
          onClick={onNewChat}
          className="px-3 py-2 rounded-xl border border-slate-300 bg-white hover:bg-slate-100 text-slate-900 font-semibold">
          + New Chat
        </button>

        <div className="text-xs text-slate-400 mt-2">Conversations</div>

        <nav className="flex-1 flex flex-col gap-2 overflow-auto pr-1">
          {conversations.map((c) => {
            const active = c.id === activeConversationId;
            return (
              <button
                key={c.id}
                onClick={() => setActiveConversationId(c.id)}
                className={[
                  "p-3 rounded-xl border text-left transition",
                  active
                    ? "border-slate-400 bg-white"
                    : "border-slate-200 hover:bg-slate-100",
                ].join(" ")}
                title={c.title}
              >
                <div className="text-sm font-semibold truncate">{c.title}</div>
                <div className="text-[11px] text-slate-400 mt-1">{c.updatedAt}</div>
              </button>
            );
          })}
        </nav>

        <div className="mt-auto flex items-center justify-between gap-3">
          <div className="text-xs text-slate-400">Guest</div>
          <button className="text-xs text-indigo-300 hover:text-indigo-200" onClick={() => alert("로그인 연결 전")}>
            Login (later)
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="min-h-0 overflow-hidden grid grid-rows-[56px_1fr_auto] bg-white">
        <header className="h-14 px-4 flex items-center justify-between bg-white">
          <div className="text-sm font-bold">{activeTitle}</div>
          <button
            className="text-xs px-3 py-2 rounded-xl border border-slate-300 bg-white hover:bg-slate-100 text-slate-700"
            onClick={() => alert("설정은 나중에")}
          >
            Settings (later)
          </button>
        </header>

        <MessageList messages={messages} />

        <MessageInput onSend={onSend} />
      </main>
    </div>
  );
}

function MessageList({ messages }: { messages: Message[] }) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <div className="min-h-0 p-4 overflow-auto">
      {messages.length === 0 ? (
        <div className="max-w-xl border border-dashed border-slate-700 rounded-2xl p-5 text-slate-200/90">
          <div className="font-bold mb-1">대화를 시작하세요</div>
          <div className="text-sm text-slate-400">
            왼쪽 목록 선택 후 메시지를 입력하면 됩니다.
          </div>
        </div>
      ) : (
        messages.map((m) => (
          <div
            key={m.id}
            className={`flex mb-2 ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-2xl rounded-2xl px-3 py-2 border ${
                m.role === "user"
                  ? "bg-white border-slate-200 text-slate-900"
                  : "bg-slate-100 border-slate-300 text-slate-900"
              }`}
            >
              <div className="text-sm whitespace-pre-wrap leading-relaxed">
                {m.content}
              </div>
              <div className="text-[11px] text-slate-400 mt-1">
                {m.createdAt}
              </div>
            </div>
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  );
}

function MessageInput({ onSend }: { onSend: (text: string) => void }) {
  const [text, setText] = useState("");

  function submit() {
    onSend(text);
    setText("");
  }

  return (
    <div className="p-3 flex gap-2 items-end bg-white">
      <textarea
        className="flex-1 resize-none rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-500"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="메시지를 입력하세요…"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <button
        onClick={submit}
        className="px-4 py-2 rounded-xl border border-slate-300 bg-slate-900 text-white hover:bg-slate-800 font-semibold text-sm"
      >
        Send
      </button>
    </div>
  );
}
