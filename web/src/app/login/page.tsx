"use client";

import { IdcardOutlined, LockOutlined } from "@ant-design/icons";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Checkbox, Input, Space, Typography } from "antd";

import { useAuth } from "@/components/auth-provider";
import { withBasePath } from "@/lib/base-path";
import type { MenuTreeItem } from "@/types/auth";

const LOGIN_REMEMBER_KEY = "login.remember";
const LOGIN_USER_ID_KEY = "login.user_id";
const LOGIN_PASSWORD_KEY = "login.password";

function findFirstMenuPath(items: MenuTreeItem[]): string | null {
  for (const item of items) {
    if (item.path) {
      return item.path;
    }
    if (item.children.length > 0) {
      const childPath = findFirstMenuPath(item.children);
      if (childPath) {
        return childPath;
      }
    }
  }
  return null;
}

export default function LoginPage() {
  const router = useRouter();
  const { user, initializing, login, fetchWithAuth } = useAuth();

  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [rememberPassword, setRememberPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!initializing && user) {
      const redirectToFirstMenu = async () => {
        try {
          const response = await fetchWithAuth("/api/v1/admin/me/menus");
          if (!response.ok) {
            router.replace("/admin/users");
            return;
          }

          const menuData = (await response.json()) as MenuTreeItem[];
          const firstRawPath = findFirstMenuPath(menuData);

          router.replace(firstRawPath || "/admin/users");
        } catch {
          router.replace("/admin/users");
        }
      };

      void redirectToFirstMenu();
    }
  }, [initializing, router, user, fetchWithAuth]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const remembered = window.localStorage.getItem(LOGIN_REMEMBER_KEY) === "1";
    if (!remembered) {
      return;
    }

    setRememberPassword(true);
    setUserId(window.localStorage.getItem(LOGIN_USER_ID_KEY) ?? "");
    setPassword(window.localStorage.getItem(LOGIN_PASSWORD_KEY) ?? "");
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setBusy(true);

    try {
      const normalizedUserId = userId.trim();
      await login(normalizedUserId, password);

      if (typeof window !== "undefined") {
        if (rememberPassword) {
          window.localStorage.setItem(LOGIN_REMEMBER_KEY, "1");
          window.localStorage.setItem(LOGIN_USER_ID_KEY, normalizedUserId);
          window.localStorage.setItem(LOGIN_PASSWORD_KEY, password);
        } else {
          window.localStorage.removeItem(LOGIN_REMEMBER_KEY);
          window.localStorage.removeItem(LOGIN_USER_ID_KEY);
          window.localStorage.removeItem(LOGIN_PASSWORD_KEY);
        }
      }

      setPassword("");
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "未知错误";
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  if (initializing) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-3xl items-center justify-center px-6 py-20">
        <Typography.Text type="secondary">正在初始化会话...</Typography.Text>
      </main>
    );
  }

  if (user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-3xl items-center justify-center px-6 py-20">
        <Typography.Text type="secondary">正在跳转到控制台...</Typography.Text>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--fquiz-theme-bg-layout)] px-4 py-8">
      <Card className="login-page-card w-full max-w-[360px]">
        <Space direction="vertical" size={20} className="w-full">
          <div className="flex justify-center">
            <img
              src={withBasePath("/favicon.ico")}
              alt="高压电塔图标"
              width={72}
              height={72}
              className="h-[72px] w-[72px]"
            />
          </div>

          <Typography.Title level={3} className="!mb-0 !text-center">
            防雷计算
          </Typography.Title>

          <form className="space-y-4" onSubmit={handleSubmit}>
            <Input
              size="large"
              value={userId}
              prefix={<IdcardOutlined />}
              placeholder="用户 ID"
              onChange={(event: ChangeEvent<HTMLInputElement>) => setUserId(event.currentTarget.value)}
              autoComplete="username"
              required
            />

            <Input.Password
              size="large"
              value={password}
              prefix={<LockOutlined />}
              placeholder="密码"
              onChange={(event: ChangeEvent<HTMLInputElement>) => setPassword(event.currentTarget.value)}
              autoComplete="current-password"
              minLength={1}
              maxLength={128}
              required
            />

            <div className="flex items-center justify-between">
              <Checkbox
                checked={rememberPassword}
                onChange={(event) => setRememberPassword(event.target.checked)}
              >
                记住密码
              </Checkbox>
            </div>

            <Button block size="large" type="primary" htmlType="submit" loading={busy}>
              登录
            </Button>
          </form>

          {error && <Alert showIcon type="error" message={error} />}
        </Space>
      </Card>
    </main>
  );
}
