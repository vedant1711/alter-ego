export interface ChatMessage {
  id: string;
  role: "user" | "twin";
  text: string;
  streaming?: boolean;
  error?: boolean;
}

/** A memory the retriever surfaced for the latest reply. */
export interface RetrievedMemory {
  text: string;
  /** Which retrieval legs found it: "graph" | "vector" | "keyword". */
  source: string[];
  score: number;
  /** How the memory was created: "sample" | "fact" | "message" | "summary". */
  source_type: string;
}
