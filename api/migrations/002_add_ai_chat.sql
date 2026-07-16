-- Create AI chat tables

CREATE TABLE IF NOT EXISTS ai_chat_conversations (
    id SERIAL PRIMARY KEY,
    title VARCHAR(256) NOT NULL DEFAULT '新对话',
    user_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_ai_chat_conversations_user_id FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_ai_chat_conversations_user_id ON ai_chat_conversations(user_id);

CREATE TABLE IF NOT EXISTS ai_chat_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_ai_chat_messages_conversation_id FOREIGN KEY (conversation_id) REFERENCES ai_chat_conversations(id) ON DELETE CASCADE
);

CREATE INDEX idx_ai_chat_messages_conversation_id ON ai_chat_messages(conversation_id);
CREATE INDEX idx_ai_chat_messages_role ON ai_chat_messages(role);

COMMENT ON TABLE ai_chat_conversations IS 'AI问答对话会话表';
COMMENT ON TABLE ai_chat_messages IS 'AI问答消息表';
COMMENT ON COLUMN ai_chat_conversations.title IS '对话标题';
COMMENT ON COLUMN ai_chat_conversations.user_id IS '用户ID';
COMMENT ON COLUMN ai_chat_messages.conversation_id IS '对话ID';
COMMENT ON COLUMN ai_chat_messages.role IS '角色：user 或 assistant';
COMMENT ON COLUMN ai_chat_messages.content IS '消息内容';
