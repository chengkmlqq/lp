-- Add function calling support fields to ai_chat_messages table

ALTER TABLE ai_chat_messages
ADD COLUMN tool_calls JSON,
ADD COLUMN tool_call_id VARCHAR(64);

COMMENT ON COLUMN ai_chat_messages.tool_calls IS 'Stores function/tool calls made by the assistant';
COMMENT ON COLUMN ai_chat_messages.tool_call_id IS 'ID for tool/function result messages';
