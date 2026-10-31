import type { NextConfig } from "next";

function normalizeBasePath(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  if (!trimmed || trimmed === "/") {
    return undefined;
  }

  const normalized = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  return normalized.replace(/\/+$/, "");
}

const basePath = normalizeBasePath(process.env.NEXT_PUBLIC_APP_BASE_PATH);

// 本地开发后端代理：dev server（无 nginx）时把 /api 转发到远端 FastAPI，
// 浏览器保持同源请求，规避 CORS；生产环境走 compose nginx（location /api/ 直达 api 容器），不会触发此 rewrite。
const devApiProxy = process.env.NEXT_PUBLIC_API_BASE_URL
  ? undefined
  : {
      source: "/api/:path*",
      destination: "http://111.170.33.2:8001/api/:path*",
    };

const nextConfig: NextConfig = {
  output: "standalone",
  basePath,
  async rewrites() {
    return devApiProxy ? [devApiProxy] : [];
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  turbopack: {
    resolveAlias: {
      "@spz-loader/core": "src/lib/spz-loader-core-shim.ts",
    },
  },
};

export default nextConfig;
