export type Role = "user" | "assistant";

export type Message = {
  id: string;
  role: Role;
  content: string;
  createdAt: string; // ISO
  status?: "streaming" | "final" | "error";
};

export type Conversation = {
  id: string;
  title: string;
  updatedAt: string; // ISO
  messages: Message[];
};
