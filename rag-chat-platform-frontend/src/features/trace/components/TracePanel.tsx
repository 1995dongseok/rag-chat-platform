import { useEffect, useMemo, useState, useRef } from "react";
import { useTraceStore, type TraceEvent } from "../store/traceStore";

type Props = {
  conversationId: string | null;
};

const EMPTY_EVENTS: TraceEvent[] = [];

export default function TracePanel({ conversationId }: Props) {
  const [round, setRound] = useState<1 | 2>(1);
  const hasAutoSwitched = useRef<string | null>(null);
  
  const events = useTraceStore((s) => {
    if (!conversationId) return EMPTY_EVENTS;
    return s.byConversation[conversationId] ?? EMPTY_EVENTS;
  });

  useEffect(() => {
    if (!conversationId || events.length === 0) {
      setRound(1);
      hasAutoSwitched.current = null;
    }
  }, [conversationId, events.length]);

  useEffect(() => {
    const hasRound2Data = events.some((e) => e.round === 2);
    if (round === 1 && hasRound2Data && hasAutoSwitched.current !== conversationId) {
      setRound(2);
      hasAutoSwitched.current = conversationId;
    }
  }, [events, round, conversationId]);

  const { retrieval, rerank, verification } = useMemo(() => {
    const filtered = events.filter((e) => e.round === round);
    return {
      retrieval: filtered.filter((e) => e.type === "retrieval"),
      rerank: filtered.filter((e) => e.type === "rerank"),
      verification: filtered
        .filter((e) => e.type === "verification")
        .at(-1) as Extract<TraceEvent, { type: "verification" }> | undefined,
    };
  }, [events, round]);

  const isPass = useMemo(() => {
    if (!verification) return false;
    const p = verification.payload as any;
    if (!p) return false;
    if (p.pass === true || String(p.pass) === "true") return true;
    if (p.payload && (p.payload.pass === true || String(p.payload.pass) === "true")) return true;
    return false;
  }, [verification]);

  const isOOS = useMemo(() => {
    const hasRetrieval = (retrieval.at(-1)?.payload as any[])?.length > 0;
    const rerankPayload = (rerank.at(-1)?.payload as any[]);
    const isEmptyRerank = rerankPayload && rerankPayload.length === 0;
    
    return hasRetrieval && isEmptyRerank;
  }, [retrieval, rerank]);

  const renderDocCard = (doc: any, index: number, isRerank: boolean) => {
    const change = doc.metadata?.rank_change ?? 0;
    return (
      <div key={index} className="mb-2 p-2 bg-white border border-slate-200 rounded-lg text-xs shadow-sm animate-fade-in-up">
        <div className="flex justify-between items-center mb-1">
          <div className="flex items-center gap-2">
            <span className={`font-bold px-1.5 py-0.5 rounded ${
              isRerank ? "bg-indigo-50 text-indigo-700" : "bg-slate-100 text-slate-600"
            }`}>
              {isRerank ? `Rank ${index + 1}` : `Retr ${index + 1}`}
            </span>
            
            {isRerank && change !== 0 && (
              <span className={`text-[10px] font-bold flex items-center ${
                change > 0 ? "text-emerald-600" : "text-rose-500"
              }`}>
                {change > 0 ? "↑" : "↓"} {Math.abs(change)}
              </span>
            )}
          </div>

          {doc.score !== undefined && (
            <span className="text-[10px] text-slate-400 font-mono bg-slate-50 px-1 rounded">
              {typeof doc.score === 'number' ? doc.score.toFixed(3) : doc.score}
            </span>
          )}
        </div>
        
        <div className="text-slate-700 line-clamp-2 mb-1 leading-snug break-all">
          {doc.content || (typeof doc === 'string' ? doc : JSON.stringify(doc))}
        </div>
        {doc.metadata?.url && (
          <div className="text-[9px] text-blue-500 truncate hover:underline cursor-pointer">
            {doc.metadata.url}
          </div>
        )}
      </div>
    );
  };

  return (
    <aside className="min-h-0 border-l border-slate-200 bg-slate-50 p-3 overflow-auto w-80 flex flex-col h-full">
      <div className="flex gap-1 mb-4 bg-slate-200 p-1 rounded-lg shrink-0">
        {[1, 2].map((r) => {
            const hasData = events.some(e => e.round === r);
            if (r === 2 && !hasData) return null;

            return (
                <button
                    key={r}
                    onClick={() => setRound(r as 1 | 2)}
                    className={`flex-1 py-1.5 text-xs font-bold rounded-md transition-all flex items-center justify-center gap-1.5 ${
                    round === r 
                        ? "bg-white text-slate-800 shadow-sm" 
                        : "text-slate-500 hover:text-slate-700"
                    }`}
                >
                    Round {r}
                    {r === 1 && hasData && (
                        <span className={`w-1.5 h-1.5 rounded-full ${isOOS || (events.some(e => e.round === 2)) ? "bg-rose-500" : "bg-emerald-500"}`} />
                    )}
                    {r === 2 && (
                        <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
                    )}
                </button>
            );
        })}
      </div>

      <div className="flex-1 overflow-y-auto pr-1 space-y-6">
        <section>
          <div className="flex items-center gap-2 mb-2 sticky top-0 bg-slate-50 py-1 z-10">
            <div className="w-1 h-4 bg-slate-300 rounded-full"></div>
            <div className="font-bold text-slate-700 text-sm">Retrieval</div>
            <span className="text-[10px] text-slate-400">({(retrieval.at(-1)?.payload as any[])?.length || 0})</span>
          </div>
          <div className="max-h-60 overflow-y-auto pr-1 custom-scrollbar">
            {retrieval.length === 0 ? (
              <div className="text-xs text-slate-400 italic py-2">— No data</div>
            ) : (
              (retrieval.at(-1)?.payload as any[]).map((doc, i) => renderDocCard(doc, i, false))
            )}
          </div>
        </section>

        <section>
          <div className="flex items-center gap-2 mb-2 sticky top-0 bg-slate-50 py-1 z-10">
            <div className={`w-1 h-4 rounded-full ${isOOS ? "bg-rose-500" : "bg-indigo-400"}`}></div>
            <div className="font-bold text-slate-700 text-sm">Rerank</div>
            {isOOS && (
                <span className="ml-auto bg-rose-100 text-rose-700 text-[10px] px-2 py-0.5 rounded-full font-bold animate-pulse">
                    ⚠️ OOS (Filtered)
                </span>
            )}
          </div>
          <div className="max-h-60 overflow-y-auto pr-1 custom-scrollbar">
            {rerank.length === 0 ? (
                isOOS ? (
                    <div className="p-3 bg-rose-50 border border-rose-100 rounded-lg text-xs text-rose-600 text-center">
                        <div className="font-bold mb-1">Low Relevance Score</div>
                        검색된 문서들의 연관성이 낮아<br/>답변 생성에서 제외되었습니다.
                    </div>
                ) : (
                    <div className="text-xs text-slate-400 italic py-2">— No reranked data</div>
                )
            ) : (
              (rerank.at(-1)?.payload as any[]).map((doc, i) => renderDocCard(doc, i, true))
            )}
          </div>
        </section>

        <section className="border-t border-slate-200 pt-4 pb-4">
          <div className="flex items-center justify-between mb-3">
            <div className="font-bold text-slate-700 text-sm">Verification</div>
            {verification && (
              <span className={`px-2 py-0.5 rounded text-[10px] font-black tracking-wider ${
                isPass ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"
              }`}>
                {isPass ? "PASS" : "FAIL"}
              </span>
            )}
          </div>

          {!verification ? (
            isOOS ? (
                <div className="text-xs text-slate-400 italic">— Skipped (OOS)</div>
            ) : (
                <div className="text-xs text-slate-400 italic">— Waiting for evaluation</div>
            )
          ) : (
            <div className="space-y-3">
              {verification.payload.ragas && (
                <div className="grid grid-cols-1 gap-2 bg-white p-2 border border-slate-200 rounded-lg shadow-sm">
                  {Object.entries(verification.payload.ragas).map(([key, val]) => (
                    <div key={key}>
                      <div className="flex justify-between text-[9px] uppercase font-bold text-slate-500 mb-0.5">
                        <span>{key.replace(/_/g, ' ')}</span>
                        <span>{Math.round((val as number) * 100)}%</span>
                      </div>
                      <div className="w-full bg-slate-100 h-1 rounded-full overflow-hidden">
                        <div 
                          className={`h-full transition-all duration-700 ${
                            (val as number) < 0.7 ? "bg-rose-400" : "bg-indigo-500"
                          }`} 
                          style={{ width: `${(val as number) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
              
              {verification.payload.reason && (
                <div className={`text-[11px] p-2 border-l-2 rounded-r-md leading-relaxed ${
                    !isPass 
                    ? "bg-rose-50 text-rose-700 border-rose-400" 
                    : "bg-white text-slate-600 border-slate-300"
                }`}>
                  <span className={`font-bold block mb-0.5 uppercase text-[9px] ${!isPass ? "text-rose-500" : "text-slate-400"}`}>
                    Comment
                  </span>
                  {verification.payload.reason}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </aside>
  );
}