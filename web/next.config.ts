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

const nextConfig: NextConfig = {
  output: "standalone",
  basePath,
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
