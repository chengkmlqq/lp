"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Input,
  List,
  Popconfirm,
  Space,
  Spin,
  Typography,
} from "antd";
import {
  PlusOutlined,
  SendOutlined,
  DeleteOutlined,
  BulbOutlined,
  MessageOutlined,
} from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { readApiError, API_BASE_URL } from "@/lib/api";
import {
  AI_CHAT_EXAMPLE_PROMPTS,
  generateConversationTitle,
  shouldShowAiChatGuide,
} from "@/lib/ai-chat";
import type {
  AiChatConversation,
  AiChatConversationListResponse,
  AiChatMessage,
} from "@/types/ai-chat";

const { TextArea } = Input;
const { Text } = Typography;

type ChatStreamEvent =
  | { type: "message"; message: AiChatMessage }
  | { type: "delta"; content: string }
  | { type: "done"; reply: AiChatMessage };

export default function AiChatPage() {
  const { user, initializing, fetchWithAuth } = useAuth();
  const queryClient = useQueryClient();

  const [selectedConvId, setSelectedConvId] = useState<number | null>(null);
  const [messageInput, setMessageInput] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [streamingMessageId, setStreamingMessageId] = useState<number | null>(null);
  const [optimisticMessages, setOptimisticMessages] = useState<Record<number, AiChatMessage[]>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useToastFeedback({
    errorMessage: error,
    successMessage: success,
    errorTitle: "操作失败",
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  const { data: conversations, isLoading: convLoading } = useQuery({
    queryKey: ["ai-chat-conversations"],
    queryFn: async () => {
      const response = await fetchWithAuth(
        `${API_BASE_URL}/api/v1/ai-chat/conversations?limit=100`
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AiChatConversationListResponse;
    },
    enabled: !!user,
  });
  const hasConversations = (conversations?.items?.length ?? 0) > 0;

  const { data: currentConv, isLoading: convDetailLoading } = useQuery({
    queryKey: ["ai-chat-conversation", selectedConvId],
    queryFn: async () => {
      if (!selectedConvId) return null;
      const response = await fetchWithAuth(
        `${API_BASE_URL}/api/v1/ai-chat/conversations/${selectedConvId}`
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AiChatConversation;
    },
    enabled: !!selectedConvId,
  });

  const createConvMutation = useMutation({
    mutationFn: async (title: string) => {
      const response = await fetchWithAuth(
        `${API_BASE_URL}/api/v1/ai-chat/conversations`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title }),
        }
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AiChatConversation;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["ai-chat-conversations"] });
      setSelectedConvId(data.id);
      setSuccess("创建对话成功");
    },
    onError: (err: Error) => {
      setError(`创建对话失败: ${err.message}`);
    },
  });

  const deleteConvMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetchWithAuth(
        `${API_BASE_URL}/api/v1/ai-chat/conversations/${id}`,
        { method: "DELETE" }
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
    },
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ["ai-chat-conversations"] });
      // Only clear selection if we deleted the currently selected conversation
      if (selectedConvId === deletedId) {
        setSelectedConvId(null);
      }
      setSuccess("删除对话成功");
    },
    onError: (err: Error) => {
      setError(`删除对话失败: ${err.message}`);
    },
  });

  const currentMessages = useMemo(
    () => (selectedConvId ? optimisticMessages[selectedConvId] ?? currentConv?.messages ?? [] : []),
    [currentConv?.messages, optimisticMessages, selectedConvId],
  );
  const showGuide = shouldShowAiChatGuide(selectedConvId, convDetailLoading, currentMessages.length);

  const updateOptimisticMessages = useCallback(
    (convId: number, updater: (messages: AiChatMessage[]) => AiChatMessage[]) => {
      setOptimisticMessages((current) => ({
        ...current,
        [convId]: updater(current[convId] ?? currentConv?.messages ?? []),
      }));
    },
    [currentConv?.messages],
  );

  const readChatStream = useCallback(
    async (convId: number, content: string) => {
      const now = new Date().toISOString();
      const assistantTempId = -Date.now();
      const userTempId = assistantTempId - 1;
      const userMessage: AiChatMessage = {
        id: userTempId,
        conversation_id: convId,
        role: "user",
        content,
        created_at: now,
      };
      const assistantMessage: AiChatMessage = {
        id: assistantTempId,
        conversation_id: convId,
        role: "assistant",
        content: "",
        created_at: now,
      };

      setStreamingMessageId(assistantTempId);
      updateOptimisticMessages(convId, (messages) => [...messages, userMessage, assistantMessage]);

      const response = await fetchWithAuth(
        `${API_BASE_URL}/api/v1/ai-chat/conversations/${convId}/messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        },
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      if (!response.body) {
        throw new Error("浏览器未返回流式响应体");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const applyStreamEvent = (event: ChatStreamEvent) => {
        if (event.type === "message") {
          updateOptimisticMessages(convId, (messages) =>
            messages.map((msg) => (msg.id === userTempId ? event.message : msg)),
          );
          return;
        }

        if (event.type === "delta") {
          updateOptimisticMessages(convId, (messages) =>
            messages.map((msg) =>
              msg.id === assistantTempId
                ? { ...msg, content: `${msg.content}${event.content}` }
                : msg,
            ),
          );
          return;
        }

        updateOptimisticMessages(convId, (messages) =>
          messages.map((msg) => (msg.id === assistantTempId ? event.reply : msg)),
        );
      };

      const parseBufferedEvents = () => {
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          applyStreamEvent(JSON.parse(trimmed) as ChatStreamEvent);
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        parseBufferedEvents();
      }

      buffer += decoder.decode();
      if (buffer.trim()) {
        applyStreamEvent(JSON.parse(buffer.trim()) as ChatStreamEvent);
      }

      await queryClient.invalidateQueries({ queryKey: ["ai-chat-conversations"] });
      await queryClient.invalidateQueries({ queryKey: ["ai-chat-conversation", convId] });
    },
    [fetchWithAuth, queryClient, updateOptimisticMessages],
  );

  const sendMessageMutation = useMutation({
    mutationFn: async ({ convId, content }: { convId: number; content: string }) => {
      await readChatStream(convId, content);
    },
    onSuccess: (_, variables) => {
      setMessageInput("");
      setStreamingMessageId(null);
      setOptimisticMessages((current) => {
        const next = { ...current };
        delete next[variables.convId];
        return next;
      });
    },
    onError: (err: Error, variables) => {
      setStreamingMessageId(null);
      setOptimisticMessages((current) => {
        const next = { ...current };
        delete next[variables.convId];
        return next;
      });
      queryClient.invalidateQueries({
        queryKey: ["ai-chat-conversation", variables.convId],
      });
      setError(`发送消息失败: ${err.message}`);
    },
  });

  const handleSendMessage = useCallback(async () => {
    const content = messageInput.trim();
    if (!content) return;

    if (!selectedConvId) {
      try {
        const newConv = await createConvMutation.mutateAsync(generateConversationTitle(content));
        sendMessageMutation.mutate({
          convId: newConv.id,
          content,
        });
      } catch {
        // Error already handled by createConvMutation
        return;
      }
    } else {
      // Send to existing conversation
      sendMessageMutation.mutate({
        convId: selectedConvId,
        content,
      });
    }
  }, [selectedConvId, messageInput, sendMessageMutation, createConvMutation]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [currentMessages]);

  // Auto-select the most recent conversation when conversations load
  useEffect(() => {
    if (!convLoading && !selectedConvId && conversations?.items?.length) {
      setSelectedConvId(conversations.items[0].id);
    }
  }, [convLoading, selectedConvId, conversations?.items]);

  const handleExamplePromptClick = useCallback(
    (prompt: string) => {
      setMessageInput(prompt);
      void (async () => {
        if (selectedConvId) {
          sendMessageMutation.mutate({
            convId: selectedConvId,
            content: prompt,
          });
          return;
        }

        try {
          const newConv = await createConvMutation.mutateAsync(generateConversationTitle(prompt));
          sendMessageMutation.mutate({
            convId: newConv.id,
            content: prompt,
          });
        } catch {
          return;
        }
      })();
    },
    [createConvMutation, selectedConvId, sendMessageMutation],
  );

  if (initializing) {
    return (
      <div className="flex min-h-[240px] items-center justify-center">
        <Spin tip="初始化中..." />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Card
        className="admin-ai-chat-page-card"
        bordered={false}
        styles={{ body: { padding: 0 } }}
      >
        <div style={{ display: "flex", minHeight: 0, flex: 1 }}>
          {/* Left Sidebar - Conversation List */}
          <div
            className="ai-chat-sidebar"
            style={{
              width: 280,
              background: "var(--fquiz-theme-bg-elevated)",
          display: "flex",
          flexDirection: "column",
          borderRight: "1px solid var(--ant-color-border-secondary)",
        }}
      >
        {/* Header with new conversation button */}
        <div
          className="ai-chat-sidebar-header"
          style={{
            padding: "16px",
            borderBottom: "1px solid var(--ant-color-border-secondary)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Text strong style={{ fontSize: 16 }}>
            AI 问答助手
          </Text>
          <Button
            type="text"
            icon={<PlusOutlined />}
            onClick={() => createConvMutation.mutate("新对话")}
            loading={createConvMutation.isPending}
          />
        </div>

        {/* Conversation List */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {convLoading ? (
            <div style={{ textAlign: "center", padding: "60px 20px" }}>
              <Spin />
            </div>
          ) : conversations?.items.length === 0 ? (
            <div style={{ padding: "60px 20px", textAlign: "center" }}>
              <Text style={{ color: "var(--ant-color-text-secondary)", fontSize: 14 }}>
                暂无对话
              </Text>
            </div>
          ) : (
            <List
              dataSource={conversations?.items || []}
              renderItem={(conv) => (
                <div
                  key={conv.id}
                  className={`ai-chat-conversation-item ${selectedConvId === conv.id ? "ai-chat-conversation-item-active" : ""}`}
                  onClick={() => setSelectedConvId(conv.id)}
                  style={{
                    cursor: "pointer",
                    background:
                      selectedConvId === conv.id
                        ? "var(--fquiz-theme-bg-active)"
                        : "transparent",
                    padding: "12px 16px",
                    transition: "background 0.2s ease",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    borderLeft: selectedConvId === conv.id ? "3px solid var(--ant-color-primary)" : "3px solid transparent",
                  }}
                  onMouseEnter={(e) => {
                    if (selectedConvId !== conv.id) {
                      e.currentTarget.style.background = "var(--fquiz-theme-bg-soft)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (selectedConvId !== conv.id) {
                      e.currentTarget.style.background = "transparent";
                    }
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 14,
                        fontWeight: 500,
                        marginBottom: 4,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {conv.title}
                    </div>
                    <div style={{ fontSize: 12, color: "var(--ant-color-text-secondary)" }}>
                      {conv.message_count || 0} 条消息
                    </div>
                  </div>
                  <Popconfirm
                    title="确认删除"
                    description="删除后将无法恢复，确定删除此对话吗？"
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      deleteConvMutation.mutate(conv.id);
                    }}
                    okText="确定"
                    cancelText="取消"
                  >
                    <Button
                      danger
                      size="small"
                      type="text"
                      icon={<DeleteOutlined />}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                </div>
              )}
            />
          )}
        </div>
      </div>

      {/* Right Side - Chat Area */}
      <div
        className="ai-chat-main-area"
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          background: "var(--fquiz-theme-bg-layout)",
          overflow: "hidden",
        }}
      >
        {showGuide ? (
          <>
            <div
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                padding: "32px 24px",
                overflowY: "auto",
              }}
            >
              <div style={{ width: "min(720px, 100%)" }}>
                <div style={{ marginBottom: 24 }}>
                  <Text style={{ display: "block", fontSize: 14, color: "var(--ant-color-text-secondary)", marginBottom: 8 }}>
                    AI 问答助手
                  </Text>
                  <Text strong style={{ display: "block", fontSize: 28, lineHeight: 1.2, marginBottom: 12 }}>
                    欢迎开始提问
                  </Text>
                  <Text style={{ display: "block", fontSize: 14, color: "var(--ant-color-text-secondary)", lineHeight: 1.8 }}>
                    {hasConversations
                      ? "选择左侧对话继续，或点击下方示例问题快速开始。"
                      : "左侧列表保持可用。点击示例问题即可自动创建会话并发送，也可以直接输入你的问题。"}
                  </Text>
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 12,
                    marginBottom: 20,
                  }}
                >
                  {AI_CHAT_EXAMPLE_PROMPTS.map((prompt) => (
                    <Button
                      key={prompt}
                      icon={<MessageOutlined />}
                      onClick={() => handleExamplePromptClick(prompt)}
                      loading={sendMessageMutation.isPending || createConvMutation.isPending}
                      style={{
                        height: "auto",
                        minHeight: 56,
                        padding: "12px 16px",
                        borderRadius: 12,
                        justifyContent: "flex-start",
                        textAlign: "left",
                        whiteSpace: "normal",
                      }}
                    >
                      {prompt}
                    </Button>
                  ))}
                </div>

                <div
                  style={{
                    display: "grid",
                    gap: 12,
                    padding: 16,
                    border: "1px solid var(--ant-color-border-secondary)",
                    borderRadius: 12,
                    background: "var(--fquiz-theme-bg-container)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <BulbOutlined />
                    <Text strong style={{ fontSize: 14 }}>
                      你可以这样开始
                    </Text>
                  </div>
                  <Text style={{ color: "var(--ant-color-text-secondary)", lineHeight: 1.8 }}>
                    输入问题后直接发送，系统会在首次问答时创建会话并保留上下文。
                  </Text>
                </div>
              </div>
            </div>

            {/* Input Area for new conversation */}
            <div
              className="ai-chat-input-area"
              style={{
                padding: "16px 24px",
                borderTop: "1px solid var(--ant-color-border-secondary)",
                background: "var(--fquiz-theme-bg-container)",
              }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                <TextArea
                  className="ai-chat-textarea"
                  value={messageInput}
                  onChange={(e) => setMessageInput(e.target.value)}
                  placeholder="输入您的问题...（Shift + Enter 换行，Enter 发送）"
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  onPressEnter={(e) => {
                    if (!e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  disabled={sendMessageMutation.isPending || createConvMutation.isPending}
                  style={{
                    flex: 1,
                    borderRadius: 12,
                    padding: "10px 14px",
                  }}
                />
                <Button
                  className="ai-chat-send-button"
                  type="primary"
                  icon={<SendOutlined />}
                  loading={sendMessageMutation.isPending || createConvMutation.isPending}
                  onClick={handleSendMessage}
                  disabled={!messageInput.trim()}
                  style={{
                    height: "auto",
                    minHeight: 40,
                    borderRadius: 12,
                    paddingLeft: 20,
                    paddingRight: 20,
                  }}
                >
                  发送
                </Button>
              </div>
            </div>
          </>
        ) : (
          <>
            {/* Chat Header */}
            <div
              className="ai-chat-header"
              style={{
                padding: "16px 24px",
                borderBottom: "1px solid var(--ant-color-border-secondary)",
                background: "var(--fquiz-theme-bg-container)",
              }}
            >
              <Text strong style={{ fontSize: 16 }}>
                {currentConv ? currentConv.title : "AI 对话"}
              </Text>
            </div>

            {/* Messages Area */}
            <div
              className="ai-chat-messages-area"
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "24px",
                background: "var(--fquiz-theme-bg-layout)",
              }}
            >
              {convDetailLoading ? (
                <div style={{ textAlign: "center", padding: 40 }}>
                  <Spin />
                </div>
              ) : (
                <Space direction="vertical" style={{ width: "100%" }} size={16}>
                  {currentMessages.map((msg) => (
                    <div
                      key={msg.id}
                      style={{
                        display: "flex",
                        justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                      }}
                    >
                      <div
                        className={msg.role === "user" ? "ai-chat-message-bubble-user" : "ai-chat-message-bubble-assistant"}
                        style={{
                          maxWidth: "70%",
                          background: msg.role === "user" ? "var(--ant-color-primary)" : "var(--fquiz-theme-bg-container)",
                          color: msg.role === "user" ? "var(--accent-contrast)" : "var(--ant-color-text)",
                          padding: "12px 16px",
                          borderRadius: 18,
                          boxShadow: "0 1px 2px rgba(0, 0, 0, 0.08)",
                        }}
                      >
                        <div
                          style={{
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-word",
                            lineHeight: 1.6,
                            fontSize: 14,
                          }}
                        >
                          {msg.content || (msg.id === streamingMessageId ? "正在回复..." : "")}
                        </div>
                        <div
                          className="ai-chat-message-timestamp"
                          style={{
                            fontSize: 11,
                            marginTop: 6,
                            opacity: 0.6,
                          }}
                        >
                          {new Date(msg.created_at).toLocaleTimeString("zh-CN")}
                        </div>
                      </div>
                    </div>
                  ))}
                  <div ref={messagesEndRef} />
                </Space>
              )}
            </div>

            {/* Input Area */}
            <div
              className="ai-chat-input-area"
              style={{
                padding: "16px 24px",
                borderTop: "1px solid var(--ant-color-border-secondary)",
                background: "var(--fquiz-theme-bg-container)",
              }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                <TextArea
                  className="ai-chat-textarea"
                  value={messageInput}
                  onChange={(e) => setMessageInput(e.target.value)}
                  placeholder="输入消息...（Shift + Enter 换行，Enter 发送）"
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  onPressEnter={(e) => {
                    if (!e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  disabled={sendMessageMutation.isPending}
                  style={{
                    flex: 1,
                    borderRadius: 12,
                    padding: "10px 14px",
                  }}
                />
                <Button
                  className="ai-chat-send-button"
                  type="primary"
                  icon={<SendOutlined />}
                  loading={sendMessageMutation.isPending}
                  onClick={handleSendMessage}
                  disabled={!messageInput.trim()}
                  style={{
                    height: "auto",
                    minHeight: 40,
                    borderRadius: 12,
                    paddingLeft: 20,
                    paddingRight: 20,
                  }}
                >
                  发送
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
      </div>
      </Card>
    </div>
  );
}
