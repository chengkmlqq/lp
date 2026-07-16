-- Insert default AI chat system parameters

INSERT INTO system_params (param_key, param_name, param_value, description, status, created_at, updated_at)
VALUES
    ('ai_chat.openai_api_key', 'OpenAI API Key', '', '用于AI问答的OpenAI API密钥。如果为空，将使用环境变量 OPENAI_API_KEY', 'disabled', NOW(), NOW()),
    ('ai_chat.model', 'AI模型', 'gpt-3.5-turbo', '使用的AI模型名称，例如: gpt-3.5-turbo, gpt-4, gpt-4-turbo', 'enabled', NOW(), NOW()),
    ('ai_chat.base_url', 'API Base URL', 'https://api.openai.com/v1', 'OpenAI API的基础URL，可配置为第三方兼容接口', 'enabled', NOW(), NOW())
ON CONFLICT (param_key) DO NOTHING;

COMMENT ON TABLE system_params IS '系统参数配置表';
