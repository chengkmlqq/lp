import { redirect } from "next/navigation";

export default function LegacyAtpViewerRedirectPage() {
  redirect("/admin/atp-models");
}
