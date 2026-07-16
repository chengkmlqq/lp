export const AI_CHAT_EXAMPLE_PROMPTS = [
  "帮我写一份防雷计算报告",
  "什么是绕击跳闸率？",
  "解释 ATP 仿真流程",
  "tpbig.exe 的输入文件格式是什么？",
] as const;

export function generateConversationTitle(content: string): string {
  const firstLine = content.trim().split(/\r?\n/, 1)[0]?.trim() ?? "";
  if (!firstLine) {
    return "新对话";
  }

  return firstLine.length > 20 ? `${firstLine.slice(0, 20)}...` : firstLine;
}

export function shouldShowAiChatGuide(
  selectedConvId: number | null,
  convDetailLoading: boolean,
  currentMessagesCount: number,
): boolean {
  return !selectedConvId || (!convDetailLoading && currentMessagesCount === 0);
}
