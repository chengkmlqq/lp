"use client";

import { IdcardOutlined, LockOutlined, MailOutlined, UserOutlined } from "@ant-design/icons";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Input, Space, Typography } from "antd";

import { useAuth } from "@/components/auth-provider";
import { withBasePath } from "@/lib/base-path";

export default function RegisterPage() {
  const router = useRouter();
  const { user, initializing, register } = useAuth();

  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!initializing && user) {
      router.replace("/users");
    }
  }, [initializing, router, user]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("两次输入的密码不一致");
      return;
    }

    if (password.length < 8) {
      setError("密码长度至少为 8 个字符");
      return;
    }

    setBusy(true);

    try {
      await register(email, username, password);
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
      <Card className="w-full max-w-[400px]">
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
            用户注册
          </Typography.Title>

          <form className="space-y-4" onSubmit={handleSubmit}>
            <Input
              size="large"
              value={email}
              prefix={<MailOutlined />}
              placeholder="邮箱"
              type="email"
              onChange={(event: ChangeEvent<HTMLInputElement>) => setEmail(event.currentTarget.value)}
              autoComplete="email"
              required
            />

            <Input
              size="large"
              value={username}
              prefix={<UserOutlined />}
              placeholder="用户名（3-64 个字符）"
              onChange={(event: ChangeEvent<HTMLInputElement>) => setUsername(event.currentTarget.value)}
              autoComplete="username"
              minLength={3}
              maxLength={64}
              required
            />

            <Input.Password
              size="large"
              value={password}
              prefix={<LockOutlined />}
              placeholder="密码（至少 8 个字符）"
              onChange={(event: ChangeEvent<HTMLInputElement>) => setPassword(event.currentTarget.value)}
              autoComplete="new-password"
              minLength={8}
              maxLength={128}
              required
            />

            <Input.Password
              size="large"
              value={confirmPassword}
              prefix={<LockOutlined />}
              placeholder="确认密码"
              onChange={(event: ChangeEvent<HTMLInputElement>) => setConfirmPassword(event.currentTarget.value)}
              autoComplete="new-password"
              minLength={8}
              maxLength={128}
              required
            />

            <Button block size="large" type="primary" htmlType="submit" loading={busy}>
              注册
            </Button>
          </form>

          {error && <Alert showIcon type="error" message={error} />}

          <div className="text-center">
            <Typography.Text type="secondary">
              已有账号？{" "}
              <Typography.Link href="/login">立即登录</Typography.Link>
            </Typography.Text>
          </div>
        </Space>
      </Card>
    </main>
  );
}
