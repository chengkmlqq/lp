"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { setAuthHooks, fetchWithAuth, postJson } from "@/lib/api";
import { withBasePath } from "@/lib/base-path";
import type { AuthTokenResponse, UserPublic } from "@/types/auth";

const AUTH_SESSION_HINT_KEY = "auth.session_hint";

type AuthContextValue = {
  user: UserPublic | null;
  accessToken: string | null;
  getAccessToken: () => string | null;
  initializing: boolean;
  login: (userId: string, password: string, captcha?: { captchaId: string; captchaCode: string }) => Promise<void>;
  register: (email: string, username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshAccessToken: () => Promise<boolean>;
  fetchWithAuth: (
    path: string,
    init?: RequestInit,
    retryOnUnauthorized?: boolean,
  ) => Promise<Response>;
  hasRole: (roleCode: string) => boolean;
  hasPermission: (permissionCode: string) => boolean;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function hasSessionHint(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.localStorage.getItem(AUTH_SESSION_HINT_KEY) === "1";
}

function persistSessionHint(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(AUTH_SESSION_HINT_KEY, "1");
}

function clearSessionHint(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(AUTH_SESSION_HINT_KEY);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);
  const accessTokenRef = useRef<string | null>(null);
  const refreshPromiseRef = useRef<Promise<boolean> | null>(null);

  const applyToken = useCallback((token: string | null) => {
    accessTokenRef.current = token;
    setAccessToken(token);
  }, []);
  const getAccessToken = useCallback(() => accessTokenRef.current, []);

  const clearAuth = useCallback(() => {
    setUser(null);
    applyToken(null);
    clearSessionHint();
  }, [applyToken]);

  const applyAuthPayload = useCallback(
    (payload: AuthTokenResponse) => {
      setUser(payload.user);
      applyToken(payload.access_token);
      persistSessionHint();
    },
    [applyToken],
  );

  const refreshAccessToken = useCallback(async (): Promise<boolean> => {
    if (refreshPromiseRef.current) {
      return refreshPromiseRef.current;
    }

    const refreshTask = (async (): Promise<boolean> => {
      const response = await fetchWithAuth("/api/v1/auth/refresh", { method: "POST" }, false);
      if (!response.ok) {
        clearAuth();
        return false;
      }

      const payload = (await response.json()) as AuthTokenResponse;
      applyAuthPayload(payload);
      return true;
    })();

    refreshPromiseRef.current = refreshTask;
    try {
      return await refreshTask;
    } finally {
      if (refreshPromiseRef.current === refreshTask) {
        refreshPromiseRef.current = null;
      }
    }
  }, [applyAuthPayload, clearAuth]);

  useEffect(() => {
    setAuthHooks({
      getAccessToken,
      refreshAccessToken,
    });
    return () => setAuthHooks(null);
  }, [getAccessToken, refreshAccessToken]);

  const login = useCallback(
    async (userId: string, password: string, captcha?: { captchaId: string; captchaCode: string }) => {
      const payload = await postJson<AuthTokenResponse>(
        "/api/v1/auth/login",
        {
          user_id: userId,
          password,
          captcha_id: captcha?.captchaId ?? "",
          captcha_code: captcha?.captchaCode ?? "",
        },
        false,
      );
      applyAuthPayload(payload);
    },
    [applyAuthPayload],
  );

  const register = useCallback(
    async (email: string, username: string, password: string) => {
      const payload = await postJson<AuthTokenResponse>(
        "/api/v1/auth/register",
        { email, username, password },
        false,
      );
      applyAuthPayload(payload);
    },
    [applyAuthPayload],
  );

  const logout = useCallback(async () => {
    try {
      await fetchWithAuth("/api/v1/auth/logout", { method: "POST" }, false);
    } finally {
      if (typeof window !== "undefined") {
        window.location.replace(withBasePath("/login"));
        return;
      }
      clearAuth();
    }
  }, [clearAuth]);

  useEffect(() => {
    const bootstrap = async () => {
      if (!hasSessionHint()) {
        setInitializing(false);
        return;
      }

      try {
        await refreshAccessToken();
      } finally {
        setInitializing(false);
      }
    };
    void bootstrap();
  }, [refreshAccessToken]);

  const hasRole = useCallback(
    (roleCode: string) => (user ? user.role_codes.includes(roleCode) : false),
    [user],
  );
  const hasPermission = useCallback(
    (permissionCode: string) =>
      user
        ? user.role_codes.includes("admin") || user.permission_codes.includes(permissionCode)
        : false,
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      accessToken,
      getAccessToken,
      initializing,
      login,
      register,
      logout,
      refreshAccessToken,
      fetchWithAuth,
      hasRole,
      hasPermission,
    }),
    [
      user,
      accessToken,
      getAccessToken,
      initializing,
      login,
      register,
      logout,
      refreshAccessToken,
      fetchWithAuth,
      hasRole,
      hasPermission,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
