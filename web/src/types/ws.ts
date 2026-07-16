export type WsTicketResponse = {
  ticket: string;
  expires_in: number;
};

export type WsEventMeta = {
  dedupe_key?: string | null;
  requires_refetch: string[];
  priority: "low" | "normal" | "high";
};

export type WsEventEnvelope = {
  id: string;
  topic: string;
  name: string;
  version: number;
  timestamp: string;
  payload: Record<string, unknown>;
  meta?: WsEventMeta | null;
};

export type WsReadyMessage = {
  type: "ready";
  connection_id: string;
  user_id: string;
  auto_topics: string[];
};

export type WsSubscribedMessage = {
  type: "subscribed";
  topics: string[];
  rejected: Array<{ topic: string; reason: string }>;
};

export type WsUnsubscribedMessage = {
  type: "unsubscribed";
  topics: string[];
  reason?: string;
};

export type WsEventMessage = {
  type: "event";
  event: WsEventEnvelope;
};

export type WsErrorMessage = {
  type: "error";
  code: string;
  message: string;
};

export type WsPongMessage = {
  type: "pong";
};

export type WsServerMessage =
  | WsReadyMessage
  | WsSubscribedMessage
  | WsUnsubscribedMessage
  | WsEventMessage
  | WsErrorMessage
  | WsPongMessage;
