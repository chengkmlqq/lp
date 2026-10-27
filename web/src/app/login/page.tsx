"use client";

import { IdcardOutlined, LockOutlined, ReloadOutlined } from "@ant-design/icons";
import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Checkbox, Input, Space, Typography } from "antd";

import { useAuth } from "@/components/auth-provider";
import { getJson } from "@/lib/api";
import { withBasePath } from "@/lib/base-path";
import { useI18n } from "@/lib/i18n";
import { LangSwitcher } from "@/components/lang-switcher";
import type { MenuTreeItem } from "@/types/auth";

const LOGIN_REMEMBER_KEY = "login.remember";
const LOGIN_USER_ID_KEY = "login.user_id";
const LOGIN_PASSWORD_KEY = "login.password";

// 登录成功/会话失效重登后的落地页：固定为「线路管理」（此前会落到「用户管理」）
const DEFAULT_LANDING_PATH = "/admin/power-lines";

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
  const { t, lang, setLang } = useI18n();

  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [captchaCode, setCaptchaCode] = useState("");
  const [captchaId, setCaptchaId] = useState("");
  const [captchaImage, setCaptchaImage] = useState("");
  const [rememberPassword, setRememberPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refreshCaptcha = useCallback(async () => {
    try {
      const data = await getJson<{ captcha_id: string; image_base64: string }>(
        "/api/v1/auth/captcha",
        undefined,
        false,
      );
      setCaptchaId(data.captcha_id);
      setCaptchaImage(`data:image/png;base64,${data.image_base64}`);
      setCaptchaCode("");
    } catch {
      setCaptchaImage("");
    }
  }, []);

  // 进入登录页时自动加载验证码
  useEffect(() => {
    void refreshCaptcha();
  }, [refreshCaptcha]);

  useEffect(() => {
    if (!initializing && user) {
      const redirectToFirstMenu = async () => {
        try {
          const response = await fetchWithAuth("/api/v1/admin/me/menus");
          if (!response.ok) {
            router.replace(DEFAULT_LANDING_PATH);
            return;
          }

          const menuData = (await response.json()) as MenuTreeItem[];
          const firstRawPath = findFirstMenuPath(menuData);

          const targetPath = firstRawPath && firstRawPath !== "/admin/users" ? firstRawPath : DEFAULT_LANDING_PATH;
          router.replace(targetPath);
        } catch {
          router.replace(DEFAULT_LANDING_PATH);
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
      if (!captchaId || !captchaCode.trim()) {
        setError(t("请输入验证码"));
        return;
      }
      await login(normalizedUserId, password, {
        captchaId,
        captchaCode: captchaCode.trim(),
      });

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
      const message = submitError instanceof Error ? submitError.message : t("未知错误");
      setError(message);
      // 验证码一次性使用,失败后立即刷新,防止旧验证码重放
      void refreshCaptcha();
    } finally {
      setBusy(false);
    }
  };

  if (initializing) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-3xl items-center justify-center px-6 py-20">
        <Typography.Text type="secondary">{t("正在初始化会话")}...</Typography.Text>
      </main>
    );
  }

  if (user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-3xl items-center justify-center px-6 py-20">
        <Typography.Text type="secondary">{t("正在跳转到控制台")}...</Typography.Text>
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
              alt={t("高压电塔图标")}
              width={72}
              height={72}
              className="h-[72px] w-[72px]"
            />
          </div>

          <Typography.Title level={3} className="!mb-0 !text-center">
            {t("防雷计算")}
          </Typography.Title>

          <form className="space-y-4" onSubmit={handleSubmit}>
            <Input
              size="large"
              value={userId}
              prefix={<IdcardOutlined />}
              placeholder={t("用户 ID")}
              onChange={(event: ChangeEvent<HTMLInputElement>) => setUserId(event.currentTarget.value)}
              autoComplete="username"
              required
            />

            <Input.Password
              size="large"
              value={password}
              prefix={<LockOutlined />}
              placeholder={t("密码")}
              onChange={(event: ChangeEvent<HTMLInputElement>) => setPassword(event.currentTarget.value)}
              autoComplete="current-password"
              minLength={1}
              maxLength={128}
              required
            />

            <div className="flex items-center gap-2">
              <Input
                className="flex-1"
                size="large"
                value={captchaCode}
                placeholder={t("验证码")}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setCaptchaCode(event.currentTarget.value)}
                autoComplete="off"
                maxLength={8}
                required
              />
              {captchaImage ? (
                <button
                  type="button"
                  className="h-[40px] shrink-0 cursor-pointer overflow-hidden rounded border border-gray-300"
                  onClick={() => void refreshCaptcha()}
                  title={t("点击刷新验证码")}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={captchaImage} alt={t("验证码")} className="h-full w-[120px] object-cover" />
                </button>
              ) : (
                <Button
                  size="large"
                  className="shrink-0"
                  icon={<ReloadOutlined />}
                  onClick={() => void refreshCaptcha()}
                >
                  {t("刷新")}
                </Button>
              )}
            </div>

            <div className="flex items-center justify-between">
              <Checkbox
                checked={rememberPassword}
                onChange={(event) => setRememberPassword(event.target.checked)}
              >
                {t("记住密码")}
              </Checkbox>
              <LangSwitcher lang={lang} onChange={setLang} compact />
            </div>

            <Button block size="large" type="primary" htmlType="submit" loading={busy}>
              {t("登录")}
            </Button>
          </form>

          {error && <Alert showIcon type="error" message={error} />}
        </Space>
      </Card>
    </main>
  );
}
