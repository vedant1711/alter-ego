export interface ChatMessage {
  id: string;
  role: "user" | "twin";
  text: string;
  streaming?: boolean;
  error?: boolean;
}
