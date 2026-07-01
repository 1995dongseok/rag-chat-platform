import { useEffect, useMemo, useRef, useState } from "react";
import TracePanel from "../features/trace/components/TracePanel";
import { useChatStore } from "../features/chat/store/chatStore";
import { useChatActions } from "../features/chat/useChatActions";
import type { Message } from "../features/chat/types";
import 'highlight.js/styles/github-dark.css';
import RagStatus from "../features/chat/components/RagStatus";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";

const CodeBlock = ({ inline, className, children }: any) => {
  const [copied, setCopied] = useState(false);
  const codeRef = useRef<HTMLElement>(null);
  const match = /language-(\w+)/.exec(className || '');

  const onCopy = () => {
    if (codeRef.current) {
      navigator.clipboard.writeText(codeRef.current.innerText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (inline || !match) {
    return <code className="bg-slate-100 px-1 rounded text-indigo-600 font-mono text-sm">{children}</code>;
  }

  return (
    <div className="my-4 rounded border border-slate-200 bg-white overflow-hidden shadow-sm">
      <div className="flex items-center justify-between px-4 py-1.5 border-b border-slate-100 bg-slate-50 text-xs font-mono">
        <span className="text-slate-500 uppercase">{match[1]}</span>
        <button onClick={onCopy} className="text-indigo-600 hover:font-bold">
          {copied ? "COPIED" : "COPY"}
        </button>
      </div>
      <pre className="p-4 overflow-auto bg-slate-900">
        <code ref={codeRef} className={className}>{children}</code>
      </pre>
    </div>
  );
};

export default function ChatLayout() {
  const currentLanguage = useChatStore((s) => s.currentLanguage);
  const setLanguage = useChatStore((s) => s.setLanguage);
  const currentStyle = useChatStore((s) => (s as any).currentStyle || "Expert"); 
  const setStyle = useChatStore((s) => (s as any).setStyle);
  const [activeDropdown, setActiveDropdown] = useState<"lang" | "style" | null>(null);
  const languages = ["Python", "Java", "JavaScript", "C#"];
  const styles = [
    { id: "Expert", name: "🧐 수석 개발자" },
    { id: "Friendly", name: "🌟 친절한 사수" },
    { id: "Strict", name: "🤖 코드 리뷰어" }
  ];
  const [now, setNow] = useState(() => new Date());
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setActiveDropdown(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const conversations = useChatStore((s) => s.conversations);
  const activeId = useChatStore((s) => s.activeId);
  const setActive = useChatStore((s) => s.setActive);
  const newChat = useChatStore((s) => s.newChat);
  const activeConversationId = activeId ?? (conversations[0]?.id ?? null);
  const activeConversation = useMemo(() => {
    if (!activeConversationId) return null;
    return conversations.find((c) => c.id === activeConversationId) ?? null;
  }, [conversations, activeConversationId]);
  const activeTitle = activeConversation?.title ?? "New Chat";
  const messages = activeConversation?.messages ?? [];
  const { send } = useChatActions();

  async function onSend(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    let cid = activeConversationId;
    if (!cid) {
      useChatStore.getState().newChat();
      cid = useChatStore.getState().activeId;
      if (!cid) return;
    }
    await send(cid, trimmed, currentLanguage, currentStyle);
  }

  return (
    <div className="h-screen overflow-hidden grid grid-cols-[320px_1fr_360px] bg-white text-slate-900">
      <aside className="min-h-0 border-r border-slate-200 bg-slate-50 p-4 flex flex-col gap-3">
        <div className="font-bold">rag-chat-platform</div>
        <button onClick={() => newChat()} className="px-3 py-2 rounded-xl border bg-white hover:bg-slate-100 font-semibold">새 채팅</button>
        <nav className="flex-1 overflow-auto">
          {conversations.map(c => (
            <button key={c.id} onClick={() => setActive(c.id)} className={`w-full p-3 mb-2 rounded-xl border text-left ${c.id === activeConversationId ? "bg-white border-slate-400" : "border-slate-200"}`}>
              <div className="text-sm font-semibold truncate">{c.title}</div>
            </button>
          ))}
        </nav>
      </aside>

      <main className="min-h-0 overflow-hidden grid grid-rows-[56px_1fr_auto] bg-white">
        <header className="h-14 px-4 flex items-center justify-between border-b border-slate-100 bg-white">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-slate-700">{activeTitle}</span>
          </div>
          <div className="flex items-center gap-3" ref={menuRef}>
            <div className="relative">
              <button onClick={() => setActiveDropdown(activeDropdown === "style" ? null : "style")} className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-200 bg-slate-50 hover:bg-slate-100 text-sm">
                <span className="text-slate-500 text-[11px] font-bold uppercase">Style:</span>
                <span className="font-semibold text-slate-700">{styles.find(t => t.id === currentStyle)?.name || "Select"}</span>
              </button>
              {activeDropdown === "style" && (
                <div className="absolute right-0 mt-2 w-56 bg-white border border-slate-200 rounded-xl shadow-xl z-50 p-1">
                  {styles.map((t) => (
                    <button key={t.id} onClick={() => { setStyle(t.id); setActiveDropdown(null); }} className={`w-full text-left p-2 rounded-lg ${currentStyle === t.id ? "bg-indigo-50 text-indigo-600 font-bold" : ""}`}>{t.name}</button>
                  ))}
                </div>
              )}
            </div>
            <div className="relative">
              <button onClick={() => setActiveDropdown(activeDropdown === "lang" ? null : "lang")} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm shadow-sm ${!currentLanguage ? "bg-amber-50 border-amber-200 text-amber-700 animate-pulse" : "bg-white border-slate-200 text-slate-700 hover:bg-slate-50"}`}>
                <span className="text-slate-500 text-[11px] font-bold uppercase">Lang:</span>
                <span className={`font-bold ${!currentLanguage ? "text-amber-700" : "text-indigo-600"}`}>{currentLanguage || "Select"}</span>
              </button>
              {activeDropdown === "lang" && (
                <div className="absolute right-0 mt-2 w-40 bg-white border border-slate-200 rounded-xl shadow-xl z-50 p-1">
                  {languages.map((lang) => (
                    <button key={lang} onClick={() => { setLanguage(lang); setActiveDropdown(null); }} className={`w-full text-left px-3 py-2 rounded-lg text-sm ${currentLanguage === lang ? "bg-indigo-600 text-white font-bold" : ""}`}>{lang}</button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </header>
        <MessageList messages={messages} activeConversationId={activeConversationId} />
        <MessageInput onSend={onSend} disabled={!currentLanguage} />
      </main>
      <TracePanel conversationId={activeConversationId} />
    </div>
  );
}

function MessageList({ messages, activeConversationId }: { messages: Message[], activeConversationId: string | null }) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);
  return (
    <div className="min-h-0 p-4 overflow-auto scroll-smooth">
      {messages.length === 0 ? (
        <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-4 opacity-60">
          <div className="max-w-md w-full border border-dashed border-slate-300 rounded-2xl p-6 text-center bg-slate-50">
            <div className="font-bold text-slate-600 mb-2">대화를 시작하세요</div>
            <p className="text-sm">상단 옵션을 선택하고 질문을 입력하세요.</p>
          </div>
        </div>
      ) : (
        messages.map((m) => (
          <div key={m.id} className={`flex mb-6 ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"} max-w-3xl w-full`}>
              {m.role === "assistant" && m.status === "streaming" && activeConversationId && <RagStatus conversationId={activeConversationId} />}
              <div className={`rounded-2xl px-5 py-4 border shadow-sm relative ${m.role === "user" ? "bg-indigo-600 border-indigo-600 text-white rounded-br-none" : "bg-white border-slate-200 text-slate-900 rounded-bl-none"}`}>
                <div className="text-sm leading-7 prose prose-slate max-w-none dark:prose-invert">
                  <ReactMarkdown rehypePlugins={[rehypeHighlight]} components={{ code: CodeBlock }}>{m.content}</ReactMarkdown>
                  {m.status === "streaming" && <span className="inline-block w-2 h-4 align-middle bg-current animate-pulse ml-1 text-indigo-400">|</span>}
                </div>
              </div>
              <div className="text-[10px] text-slate-400 mt-1.5 px-1 select-none">{m.createdAt}{m.status === "error" ? " · error" : ""}</div>
            </div>
          </div>
        ))
      )}
      <div ref={bottomRef} className="h-px" />
    </div>
  );
}

function MessageInput({ onSend, disabled }: { onSend: (text: string) => void | Promise<void>, disabled: boolean }) {
  const [text, setText] = useState("");
  async function submit() {
    if (disabled || !text.trim()) return;
    const t = text;
    setText("");
    await onSend(t);
  }
  return (
    <div className={`p-4 bg-white border-t border-slate-100 ${disabled ? "opacity-70" : ""}`}>
      <div className="relative flex gap-2 items-end max-w-4xl mx-auto">
        <textarea disabled={disabled} className="flex-1 resize-none rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none focus:border-indigo-500 focus:bg-white transition-all disabled:bg-slate-100" rows={1} style={{ minHeight: "48px", maxHeight: "120px" }} value={text} onChange={(e) => { setText(e.target.value); e.target.style.height = 'auto'; e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`; }} placeholder={disabled ? "언어를 먼저 선택해주세요." : "메시지를 입력하세요..."} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(); } }} />
        <button disabled={disabled || !text.trim()} onClick={() => void submit()} className="h-12 px-6 rounded-2xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-slate-200 font-bold text-sm transition-colors">
          SEND
        </button>
      </div>
    </div>
  );
}