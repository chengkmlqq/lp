function normalizeBasePath(value: string | undefined): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed || trimmed === "/") {
    return "";
  }

  return `/${trimmed.replace(/^\/+|\/+$/g, "")}`;
}

export const APP_BASE_PATH = normalizeBasePath(
  process.env.NEXT_PUBLIC_APP_BASE_PATH,
);

export function withBasePath(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("//")) {
    return path;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (!APP_BASE_PATH) {
    return normalizedPath;
  }

  if (normalizedPath === "/") {
    return APP_BASE_PATH;
  }

  return `${APP_BASE_PATH}${normalizedPath}`;
}
