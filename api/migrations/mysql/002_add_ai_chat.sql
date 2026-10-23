-- Create AI chat tables

CREATE TABLE IF NOT EXISTS ai_chat_conversations (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(256) NOT NULL DEFAULT '新对话',
    user_id VARCHAR(36) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT NOW(),
    updated_at DATETIME NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_ai_chat_conversations_user_id FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_ai_chat_conversations_user_id ON ai_chat_conversations(user_id);

CREATE TABLE IF NOT EXISTS ai_chat_messages (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_ai_chat_messages_conversation_id FOREIGN KEY (conversation_id) REFERENCES ai_chat_conversations(id) ON DELETE CASCADE
);

CREATE INDEX idx_ai_chat_messages_conversation_id ON ai_chat_messages(conversation_id);
CREATE INDEX idx_ai_chat_messages_role ON ai_chat_messages(role);

ALTER TABLE ai_chat_conversations COMMENT = 'AI问答对话会话表';
ALTER TABLE ai_chat_messages COMMENT = 'AI问答消息表';
-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）
-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）
-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）
-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）
-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）
