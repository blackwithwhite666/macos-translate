/** События, которые gateway присылает по WebSocket (и через SSE /translate). */
export type ServerEvent =
  | { type: "status"; phase: "detecting" | "loading-model" | "generating"; seq?: number }
  | {
      type: "detect";
      language: string | null;
      lingua_name: string | null;
      confidence: number;
      used_as_source: string;
      seq?: number;
    }
  | { type: "token"; text: string; seq?: number }
  | {
      type: "done";
      translation: string;
      src: string;
      tgt: string;
      prompt_tokens: number | null;
      gen_tokens: number | null;
      duration_ms: number;
      seq?: number;
    }
  | { type: "error"; message: string; seq?: number }
  | { type: "pending"; text: string };

export type ClientMessage =
  | {
      type: "translate";
      text: string;
      src: string; // "auto" | имя языка
      tgt: string;
      seq: number;
    };
