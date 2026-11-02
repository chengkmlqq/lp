"use client";

/**
 * 语言切换器：纯图标按钮 + 下拉菜单。
 *
 * 图标选用 TranslationOutlined（A/文）：在 14~16px 下仍清晰可辨，
 * 而 GlobalOutlined（地球）的经纬线在小尺寸会糊成一团实心。
 * 按钮只占一个图标位，点击弹出「中文 / English」菜单；
 * hover 与 tooltip 说明用途，选中语言在菜单里高亮。
 * 交互对齐 header 里已有的消息铃铛（type="text" 图标按钮）与账号菜单（Dropdown bottomRight）。
 *
 * admin 布局 header 与登录/注册页角落共用。
 */
import { Button, Dropdown } from "antd";
import { TranslationOutlined } from "@ant-design/icons";

import type { AppLang } from "@/lib/i18n";

const LANG_OPTIONS: { key: AppLang; label: string }[] = [
  { key: "zh", label: "中文" },
  { key: "en", label: "English" },
];

export function LangSwitcher({
  lang,
  onChange,
}: {
  lang: AppLang;
  onChange: (next: AppLang) => void;
}) {
  const current = LANG_OPTIONS.find((option) => option.key === lang) ?? LANG_OPTIONS[0];

  return (
    <Dropdown
      trigger={["click"]}
      placement="bottomRight"
      arrow={{ pointAtCenter: true }}
      menu={{
        selectable: true,
        selectedKeys: [lang],
        items: LANG_OPTIONS.map((option) => ({ key: option.key, label: option.label })),
        onClick: ({ key }) => {
          if (key !== lang) onChange(key as AppLang);
        },
      }}
    >
      <Button
        type="text"
        className="lang-switcher"
        icon={<TranslationOutlined />}
        title="切换语言 / Switch language"
        aria-label={`切换语言 / Switch language，当前 ${current.label}`}
        aria-haspopup="menu"
      />
    </Dropdown>
  );
}
