import { NextRequest, NextResponse } from "next/server";

import { normalizeAppRoutePath } from "./lib/app-route-path";

function normalizeBasePath(value: string | undefined): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed || trimmed === "/") {
    return "";
  }

  return `/${trimmed.replace(/^\/+|\/+$/g, "")}`;
}

const APP_BASE_PATH = normalizeBasePath(process.env.NEXT_PUBLIC_APP_BASE_PATH);

const RESERVED_PREFIXES = [
  "/api",
  "/_next",
  "/favicon.ico",
  "/robots.txt",
  "/sitemap.xml",
];

const PUBLIC_FILE = /\.[^/]+$/;

function stripBasePath(pathname: string): string {
  if (!APP_BASE_PATH) {
    return pathname;
  }

  if (pathname === APP_BASE_PATH) {
    return "/";
  }

  if (pathname.startsWith(`${APP_BASE_PATH}/`)) {
    return pathname.slice(APP_BASE_PATH.length) || "/";
  }

  return pathname;
}

function isBypassedPath(pathname: string): boolean {
  if (pathname === "/login" || pathname === "/login/") {
    return true;
  }
  if (PUBLIC_FILE.test(pathname)) {
    return true;
  }
  return RESERVED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function isAuthenticated(request: NextRequest): boolean {
  const accessToken = request.cookies.get("access_token")?.value;
  return !!accessToken;
}

export function middleware(request: NextRequest) {
  const pathname = stripBasePath(request.nextUrl.pathname);

  if (isBypassedPath(pathname)) {
    return NextResponse.next();
  }

  // Check authentication for root path
  if (pathname === "/" || pathname === "") {
    if (!isAuthenticated(request)) {
      const url = request.nextUrl.clone();
      url.pathname = APP_BASE_PATH ? `${APP_BASE_PATH}/login` : "/login";
      return NextResponse.redirect(url);
    }
  }

  // Check authentication for all other protected paths
  if (!isAuthenticated(request)) {
    const url = request.nextUrl.clone();
    url.pathname = APP_BASE_PATH ? `${APP_BASE_PATH}/login` : "/login";
    return NextResponse.redirect(url);
  }

  const canonicalPath = normalizeAppRoutePath(pathname) ?? pathname;

  // If the path already starts with /admin or matches the canonical path,
  // serve it directly — no redirect needed, no rewrite needed.
  if (pathname.startsWith("/admin/")) {
    return NextResponse.next();
  }

  // Redirect legacy/alias-only paths to their canonical form.
  if (canonicalPath !== pathname) {
    const url = request.nextUrl.clone();
    url.pathname = canonicalPath;
    return NextResponse.redirect(url);
  }

  // Internal rewrite: serve the admin layout for public /:path URLs.
  const url = request.nextUrl.clone();
  url.pathname = `/admin${canonicalPath}`;
  return NextResponse.rewrite(url);
}

export const config = {
  matcher: "/:path*",
};
