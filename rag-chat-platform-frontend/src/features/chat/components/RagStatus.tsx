import { useMemo } from "react";
import { useTraceStore } from "../../trace/store/traceStore";

type Props = {
  conversationId: string;
};

const EMPTY_EVENTS: any[] = []; 

export default function RagStatus({ conversationId }: Props) {
  const events = useTraceStore((s) => s.byConversation[conversationId] ?? EMPTY_EVENTS);

  const currentStatus = useMemo(() => {
    if (events.length === 0) return null;

    const lastEvent = events[events.length - 1];

    switch (lastEvent.type) {
      case "retrieval":
        return { text: "Searching documents...", color: "bg-blue-50 text-blue-700", icon: "🔍" };
      
      case "rerank":
        return { text: "Reranking relevance...", color: "bg-purple-50 text-purple-700", icon: "⚖️" };
      
      case "verification": {
        const p = lastEvent.payload as any;
        const isPass = p?.pass === true || p?.payload?.pass === true || String(p?.pass) === "true";

        if (!isPass) {
          return { text: "Verification Failed (Retrying...)", color: "bg-amber-50 text-amber-700", icon: "⚠️" };
        }
        return { text: "Verified & Answering", color: "bg-emerald-50 text-emerald-700", icon: "✅" };
      }

      default:
        return null;
    }
  }, [events]);

  if (!currentStatus) return null;

  return (
    <div className="flex items-center gap-2 mb-2 transition-all duration-300">
      <div className={`px-2.5 py-1 rounded-lg text-[11px] font-bold flex items-center gap-1.5 border border-current/10 shadow-sm ${currentStatus.color}`}>
        <span className="animate-pulse">{currentStatus.icon}</span>
        <span>{currentStatus.text}</span>
      </div>
    </div>
  );
}