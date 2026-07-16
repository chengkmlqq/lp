import type { Metadata } from "next";
import { Theme } from "@/components/ui-antd";

import { AppQueryProvider } from "@/components/app-query-provider";
import { AuthProvider } from "@/components/auth-provider";
import { ChunkLoadRecovery } from "@/components/chunk-load-recovery";
import { WSProvider } from "@/components/ws-provider";

// antd React 19 兼容补丁
import "@ant-design/v5-patch-for-react-19";

import "antd/dist/reset.css";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "防雷计算",
  description: "Quiz admin workspace",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        <Theme accentColor="electric" grayColor="slate" radius="medium" scaling="100%">
          <div className="flex min-h-full flex-col">
            <ChunkLoadRecovery />
            <AppQueryProvider>
              <AuthProvider>
                <WSProvider>{children}</WSProvider>
              </AuthProvider>
            </AppQueryProvider>
          </div>
        </Theme>
      </body>
    </html>
  );
}
