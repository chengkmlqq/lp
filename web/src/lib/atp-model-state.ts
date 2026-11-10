import type { AtpAssetPublishState } from "@/types/auth";

/**
 * ATP 模型发布生命周期四态（2026-11-10）。
 *
 * 原来只有「已发布 / 未发布」两态，看不出「新建的还没发过」和「发过但文件又被改了」
 * 这两种完全不同的处境。现在统一成四态：
 *   new       新建 —— 从未发布过，不参与仿真
 *   changed   变更 —— 已发布模型文件被更新后派生出的新版本，等重新发布；
 *                     仿真此时仍用上一个已发布版本（不会断档）
 *   published 已发布 —— 文件即发布内容，参与仿真定位
 *   offline   下线 —— 人工下线，保留文件但不参与仿真
 *
 * 配色沿用既有 chip 语义：绿=可用于线上、橙=待处理、灰=还没上线、红=不可用。
 */
export type AtpPublishStateMeta = {
  text: string;
  className: string;
  hint: string;
};

type Translate = (key: string) => string;

export function publishStateMeta(
  state: AtpAssetPublishState | undefined,
  t: Translate,
): AtpPublishStateMeta {
  switch (state) {
    case "published":
      return {
        text: t("已发布"),
        className: "is-published",
        hint: t("文件即发布内容，参与仿真定位"),
      };
    case "changed":
      return {
        text: t("变更"),
        className: "is-warning",
        hint: t("文件已更新，等待重新发布；仿真当前仍使用上一个已发布版本"),
      };
    case "offline":
      return {
        text: t("下线"),
        className: "is-danger",
        hint: t("已下线，不参与仿真定位；可重新发布上线"),
      };
    default:
      return {
        text: t("新建"),
        className: "is-muted",
        hint: t("尚未发布，不参与仿真定位"),
      };
  }
}

/**
 * 读取状态并兼容老响应：接口没给 publish_state 时按 is_published 推断，
 * 避免前端在灰度/缓存期间把已发布模型显示成「新建」。
 */
export function resolvePublishState(asset: {
  publish_state?: AtpAssetPublishState;
  is_published?: boolean;
}): AtpAssetPublishState {
  if (asset.publish_state) return asset.publish_state;
  return asset.is_published === false ? "new" : "published";
}

/** 该状态是否可被仿真选用（对应后端 is_published 语义） */
export function isPublishStateUsable(state: AtpAssetPublishState): boolean {
  return state === "published";
}
