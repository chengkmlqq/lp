const APP_ROUTE_ALIASES: Record<string, string> = {
  "/admin": "/users",
  "/dashboard": "/users",
  "/user": "/users",
  "/role": "/roles",
  "/menu": "/menus",
  "/system-param": "/system-params",
  "/system-message": "/system-messages",
  "/power-line": "/power-lines",
  "/power-lines/atp-viewer": "/atp-models",
  "/lightning-current": "/lightning-currents",
  "/worker": "/workers",
  "/tower-model": "/tower-models",
  "/file": "/files",
};

function trimTrailingSlash(pathname: string): string {
  if (pathname === "/") {
    return pathname;
  }
  return pathname.replace(/\/+$/, "") || "/";
}

export function normalizeAppRoutePath(path: string | null): string | null {
  if (!path) {
    return path;
  }

  if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("//")) {
    return path;
  }

  const normalizedPath = trimTrailingSlash(path.startsWith("/") ? path : `/${path}`);
  const publicPath = normalizedPath.startsWith("/admin/")
    ? trimTrailingSlash(normalizedPath.slice("/admin".length) || "/")
    : normalizedPath;

  return APP_ROUTE_ALIASES[publicPath] ?? publicPath;
}
