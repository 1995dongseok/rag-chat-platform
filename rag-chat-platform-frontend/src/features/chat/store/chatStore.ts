import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Conversation, Message } from "../types";

type MessagePatch = Partial<Message> | ((prev: Message) => Partial<Message>);

type ChatState = {
  conversations: Conversation[];
  activeId: string | null;
  newChat: () => void;
  setActive: (id: string) => void;
  appendMessage: (conversationId: string, msg: Message) => void;
  patchMessage: (conversationId: string, messageId: string, patch: MessagePatch) => void;
  patchConversation: (id: string, patch: Partial<Conversation>) => void; // 타입 추가
  currentLanguage: string | null;
  setLanguage: (lang: string) => void;
  currentStyle: string; 
  setStyle: (styleId: string) => void;
};

function nowIso() {
  return new Date().toISOString();
}

function newConversation(): Conversation {
  const id = crypto.randomUUID();
  return { id, title: "New Chat", updatedAt: nowIso(), messages: [] };
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      conversations: [newConversation()],
      activeId: null,
      currentLanguage: null,
      currentStyle: "Expert",

      setLanguage: (lang) => set({ currentLanguage: lang }),

      setStyle: (style) => set({ currentStyle: style }),

      newChat: () =>
        set((s) => {
          const c = newConversation();
          return { conversations: [c, ...s.conversations], activeId: c.id };
        }),

      setActive: (id) => set({ activeId: id }),

      appendMessage: (conversationId, msg) =>
        set((s) => ({
          conversations: s.conversations.map((c) =>
            c.id !== conversationId
              ? c
              : { ...c, updatedAt: nowIso(), messages: [...c.messages, msg] }
          ),
        })),

      patchMessage: (conversationId, messageId, patch) =>
        set((s) => ({
          conversations: s.conversations.map((c) => {
            if (c.id !== conversationId) return c;
            return {
              ...c,
              messages: c.messages.map((m) => {
                if (m.id !== messageId) return m;
                const next = typeof patch === "function" ? patch(m) : patch;
                return { ...m, ...next };
              }),
              updatedAt: nowIso(),
            };
          }),
        })),

      patchConversation: (id: string, patch: Partial<Conversation>) =>
        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.id === id ? { ...c, ...patch } : c
          ),
        })),
    }),
    { name: "rag-chat-platform-chat" }
  )
);