"use client";

import { useEffect } from "react";

import { useWS } from "@/components/ws-provider";
import type { WsEventEnvelope } from "@/types/ws";

export function useTopicSubscription(
  topic: string,
  handler: (event: WsEventEnvelope) => void,
) {
  const { subscribeTopic } = useWS();

  useEffect(() => subscribeTopic(topic, handler), [handler, subscribeTopic, topic]);
}
