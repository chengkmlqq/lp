import assert from "node:assert/strict";
import test from "node:test";

import {
  AI_CHAT_EXAMPLE_PROMPTS,
  generateConversationTitle,
  shouldShowAiChatGuide,
} from "./ai-chat.ts";

test("generateConversationTitle prefers the first line and truncates long prompts", () => {
  assert.equal(generateConversationTitle("  解释 ATP 仿真流程  "), "解释 ATP 仿真流程");
  assert.equal(
    generateConversationTitle("这是一个非常长的首行标题，需要被正确截断并保留开头\n第二行内容"),
    "这是一个非常长的首行标题，需要被正确截断...",
  );
  assert.equal(generateConversationTitle(" \n\t "), "新对话");
});

test("AI chat example prompts cover the expected onboarding scenarios", () => {
  assert.ok(AI_CHAT_EXAMPLE_PROMPTS.length >= 3);
  assert.ok(AI_CHAT_EXAMPLE_PROMPTS.includes("帮我写一份防雷计算报告"));
  assert.ok(AI_CHAT_EXAMPLE_PROMPTS.includes("什么是绕击跳闸率？"));
  assert.ok(AI_CHAT_EXAMPLE_PROMPTS.includes("解释 ATP 仿真流程"));
});

test("shouldShowAiChatGuide keeps the guide visible for empty conversations", () => {
  assert.equal(shouldShowAiChatGuide(null, false, 0), true);
  assert.equal(shouldShowAiChatGuide(12, true, 0), false);
  assert.equal(shouldShowAiChatGuide(12, false, 0), true);
  assert.equal(shouldShowAiChatGuide(12, false, 2), false);
});
