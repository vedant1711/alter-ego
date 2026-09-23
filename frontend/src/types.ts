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

export interface GraphNode {
  id: string;
  label: string;
  type: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  warnings?: Warning[];
}

/** A degradation worth telling the user about, from the server or the client. */
export interface Warning {
  code: string;
  message: string;
  action?: string | null;
}
