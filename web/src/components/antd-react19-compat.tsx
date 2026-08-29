"use client";

// antd v5 在 React 19 下的兼容补丁。
// 必须在客户端组件中导入：layout.tsx 是 Server Component，
// 其 import 只在服务端执行、不会进入浏览器 bundle，
// 导致浏览器端渲染 antd 静态 API（message/notification/Modal.confirm 等）
// 时仍触发 "[antd: compatible] antd v5 support React is 16 ~ 18" 警告。
import "@ant-design/v5-patch-for-react-19";

export function AntdReact19Compat() {
  return null;
}
