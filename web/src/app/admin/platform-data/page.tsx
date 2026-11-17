import { redirect } from "next/navigation";

// 旧「基础数据包」入口重定向到导出页；导入页已拆到 /admin/platform-data/import。
export default function LegacyPlatformDataRedirectPage() {
  redirect("/admin/platform-data/export");
}
