import { useRef } from "react";
import { useChatStore } from "./store/chatStore";
import { postSSE } from "../../shared/api/sseClient";
import { useTraceStore } from "../trace/store/traceStore";

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null;
}

function isTokenData(x: unknown): x is { delta: string } {
  return isRecord(x) && typeof x.delta === "string";
}

function isErrorData(x: unknown): x is { message: string } {
  return isRecord(x) && typeof x.message === "string";
}

function isFinalData(x: unknown): x is { content?: string } {
  return isRecord(x) && (x.content === undefined || typeof x.content === "string");
}

export function useChatActions() {
  const abortRef = useRef<AbortController | null>(null);
  const { appendMessage, patchMessage } = useChatStore();
  const addTraceEvent = useTraceStore((s) => s.addEvent);
  const clearTrace = useTraceStore((s) => s.clear);
  const currentLanguage = useChatStore((s) => s.currentLanguage);
  const currentStyle = useChatStore((s) => s.currentStyle);

  async function send(conversationId: string, text: string) {
    if (!currentLanguage) {
      alert("질문 전 상단 메뉴에서 언어를 먼저 선택해주세요!");
      return;
    }

    clearTrace(conversationId);

    const userMsgId = crypto.randomUUID();
    appendMessage(conversationId, {
      id: userMsgId,
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
      status: "final",
    });

    const asstMsgId = crypto.randomUUID();
    appendMessage(conversationId, {
      id: asstMsgId,
      role: "assistant",
      content: "",
      createdAt: new Date().toISOString(),
      status: "streaming",
    });

    abortRef.current?.abort();
    abortRef.current = new AbortController();
    try {
      await postSSE(
        "/api/chat/stream",
        { 
          conversationId, 
          messageId: asstMsgId, 
          message: text, 
          language: currentLanguage,
          style: currentStyle
        },
        ({ event, data }) => {

          if (event === "title" && isRecord(data)) {
            const newTitle = String(data.title);
            useChatStore.getState().patchConversation(conversationId, {
                title: newTitle
            });
            return;
          }

          if (event === "token" && isTokenData(data)) {
            patchMessage(conversationId, asstMsgId, (m) => ({
              content: m.content + data.delta,
            }));
            return;
          }

          if (event === "final" && isFinalData(data)) {
            patchMessage(conversationId, asstMsgId, (m) => ({
              status: "final",
              content: data.content ?? m.content,
            }));
            return;
          }

          if (event === "error" && isErrorData(data)) {
            patchMessage(conversationId, asstMsgId, {
              status: "error",
              content: data.message,
            });
            return;
          }

          if (event === "retrieval" || event === "rerank" || event === "verification") {
            const d = data as any;
            const round = d.round || 1;
            const payload = d.payload || d;
            
            addTraceEvent(conversationId, {
              type: event as any,
              round: round as any,
              payload: payload
            });
          }
        },
        abortRef.current.signal
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "SSE request failed";
      patchMessage(conversationId, asstMsgId, {
        status: "error",
        content: `❌ ${msg}`,
      });
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  return { send, stop };
}