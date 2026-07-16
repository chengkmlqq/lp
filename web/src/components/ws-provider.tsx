"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useAuth } from "@/components/auth-provider";
import { getApiBaseUrl } from "@/lib/api";
import type { WsEventEnvelope, WsServerMessage, WsTicketResponse } from "@/types/ws";

type TopicHandler = (event: WsEventEnvelope) => void;

type WSContextValue = {
  connected: boolean;
  subscribeTopic: (topic: string, handler: TopicHandler) => () => void;
  sendPing: () => void;
};

const WSContext = createContext<WSContextValue | undefined>(undefined);

function toWebSocketUrl(path: string): string {
  const base = getApiBaseUrl();
  const url = new URL(path, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function WSProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const { user, fetchWithAuth, logout, refreshAccessToken } = useAuth();
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const desiredTopicsRef = useRef<Set<string>>(new Set());
  const handlersRef = useRef<Map<string, Set<TopicHandler>>>(new Map());
  const seenEventIdsRef = useRef<string[]>([]);
  const userIdRef = useRef<string | null>(null);
  const connectRef = useRef<(() => Promise<void>) | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    userIdRef.current = user?.id ?? null;
  }, [user]);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const rememberEventId = (eventId: string) => {
    seenEventIdsRef.current.push(eventId);
    if (seenEventIdsRef.current.length > 200) {
      seenEventIdsRef.current.shift();
    }
  };

  const hasSeenEvent = (eventId: string) => seenEventIdsRef.current.includes(eventId);

  const connect = useCallback(async () => {
    if (!userIdRef.current) {
      return;
    }
    if (socketRef.current) {
      if (
        socketRef.current.readyState === WebSocket.OPEN
        || socketRef.current.readyState === WebSocket.CONNECTING
      ) {
        return;
      }
    }

    const ticketRes = await fetchWithAuth("/api/v1/ws/ticket", { method: "POST" });
    if (!ticketRes.ok) {
      return;
    }
    const ticketPayload = (await ticketRes.json()) as WsTicketResponse;
    const socket = new WebSocket(`${toWebSocketUrl("/api/v1/ws")}?ticket=${encodeURIComponent(ticketPayload.ticket)}`);
    socketRef.current = socket;

    socket.onopen = () => {
      setConnected(true);
      reconnectAttemptRef.current = 0;
      const topics = Array.from(desiredTopicsRef.current);
      if (topics.length > 0) {
        socket.send(JSON.stringify({ type: "subscribe", topics }));
      }
    };

    socket.onmessage = (message) => {
      let parsed: WsServerMessage;
      try {
        parsed = JSON.parse(message.data) as WsServerMessage;
      } catch {
        return;
      }

      if (parsed.type === "ready") {
        const topics = Array.from(desiredTopicsRef.current);
        if (topics.length > 0) {
          socket.send(JSON.stringify({ type: "subscribe", topics }));
        }
        return;
      }

      if (parsed.type === "unsubscribed") {
        for (const topic of parsed.topics) {
          desiredTopicsRef.current.delete(topic);
          handlersRef.current.delete(topic);
        }
        return;
      }

      if (parsed.type === "event") {
        const event = parsed.event;
        if (hasSeenEvent(event.id)) {
          return;
        }
        rememberEventId(event.id);

        if (event.topic === "auth") {
          if (event.name === "auth.permission_changed") {
            void refreshAccessToken();
          }
          if (event.name === "auth.profile_changed") {
            const status = typeof event.payload.status === "string" ? event.payload.status : null;
            if (status && status !== "active") {
              void logout();
              return;
            }
            void refreshAccessToken();
          }
        }

        if (event.meta?.requires_refetch) {
          for (const key of event.meta.requires_refetch) {
            void queryClient.invalidateQueries({
              predicate: (query) => {
                const first = query.queryKey[0];
                return typeof first === "string" && (first === key || first.startsWith(`${key}?`));
              },
            });
          }
        }

        const handlers = handlersRef.current.get(event.topic);
        if (handlers) {
          for (const handler of handlers) {
            handler(event);
          }
        }
      }
    };

    socket.onclose = async (event) => {
      setConnected(false);
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
      if (!userIdRef.current) {
        return;
      }
      if (event.code === 4403) {
        await logout();
        return;
      }
      const delays = [1000, 2000, 5000, 10000, 20000];
      const delay = delays[Math.min(reconnectAttemptRef.current, delays.length - 1)];
      reconnectAttemptRef.current += 1;
      clearReconnectTimer();
      reconnectTimerRef.current = window.setTimeout(() => {
        void connectRef.current?.();
      }, delay);
    };
  }, [clearReconnectTimer, fetchWithAuth, logout, queryClient, refreshAccessToken]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    if (!user) {
      clearReconnectTimer();
      socketRef.current?.close();
      socketRef.current = null;
      desiredTopicsRef.current.clear();
      handlersRef.current.clear();
      if (connected) {
        queueMicrotask(() => setConnected(false));
      }
      return;
    }
    void connect();
    return () => {
      clearReconnectTimer();
    };
  }, [clearReconnectTimer, connect, connected, user]);

  const subscribeTopic = useCallback((topic: string, handler: TopicHandler) => {
    let handlers = handlersRef.current.get(topic);
    if (!handlers) {
      handlers = new Set();
      handlersRef.current.set(topic, handlers);
    }
    handlers.add(handler);

    const isNewTopic = !desiredTopicsRef.current.has(topic);
    desiredTopicsRef.current.add(topic);
    if (isNewTopic && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: "subscribe", topics: [topic] }));
    }

    return () => {
      const currentHandlers = handlersRef.current.get(topic);
      if (!currentHandlers) {
        return;
      }
      currentHandlers.delete(handler);
      if (currentHandlers.size > 0) {
        return;
      }
      handlersRef.current.delete(topic);
      desiredTopicsRef.current.delete(topic);
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: "unsubscribe", topics: [topic] }));
      }
    };
  }, []);

  const sendPing = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: "ping", ts: Date.now() }));
    }
  }, []);

  const value = useMemo<WSContextValue>(
    () => ({ connected, subscribeTopic, sendPing }),
    [connected, sendPing, subscribeTopic],
  );

  return <WSContext.Provider value={value}>{children}</WSContext.Provider>;
}

export function useWS(): WSContextValue {
  const context = useContext(WSContext);
  if (!context) {
    throw new Error("useWS must be used inside WSProvider");
  }
  return context;
}
