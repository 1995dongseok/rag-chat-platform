import { create } from "zustand";

export type Round = 1 | 2;

export type TraceEvent =
  | { type: "retrieval"; round: Round; payload: unknown }
  | { type: "rerank"; round: Round; payload: unknown }
  | {
      type: "verification";
      round: Round;
      payload: { pass: boolean; reason?: string; ragas?: Record<string, number> };
    };

type TraceState = {
  byConversation: Record<string, TraceEvent[]>;
  addEvent: (conversationId: string, evt: TraceEvent) => void;
  clear: (conversationId: string) => void;
};

export const useTraceStore = create<TraceState>()((set) => ({
  byConversation: {},

  addEvent: (conversationId, evt) =>
    set((s) => ({
      byConversation: {
        ...s.byConversation,
        [conversationId]: [...(s.byConversation[conversationId] ?? []), evt],
      },
    })),

  clear: (conversationId) =>
    set((s) => {
      const next = { ...s.byConversation };
      delete next[conversationId];
      return { byConversation: next };
    }),
}));
