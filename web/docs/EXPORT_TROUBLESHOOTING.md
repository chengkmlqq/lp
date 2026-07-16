# 故障分析导出功能故障排查指南

## 问题：点击"导出报告"按钮没有反应

### 排查步骤

#### 1. 强制刷新浏览器页面
- **Windows/Linux**: 按 `Ctrl + Shift + R`
- **Mac**: 按 `Cmd + Shift + R`
- 这会清除浏览器缓存并重新加载所有资源

#### 2. 检查浏览器控制台错误
1. 按 `F12` 打开开发者工具
2. 切换到 **Console（控制台）** 标签
3. 查看是否有红色错误信息
4. 常见错误：
   - `Cannot find module` - 模块未找到
   - `Uncaught ReferenceError` - 引用错误
   - `Failed to load resource` - 资源加载失败

#### 3. 检查网络请求
1. 在开发者工具中切换到 **Network（网络）** 标签
2. 刷新页面
3. 确认以下文件是否成功加载（状态码200）：
   - 主页面 HTML
   - JavaScript 文件
   - 没有红色的失败请求

#### 4. 确认依赖已安装
在服务器端运行：
```bash
cd /home/jenkins/chengkai/lp/web
npm list jspdf html2canvas docx file-saver
```

应该看到所有包都已安装。

#### 5. 检查是否有弹窗被阻止
- 浏览器可能阻止了文件下载弹窗
- 查看地址栏右侧是否有弹窗阻止图标
- 如果有，点击允许弹窗

#### 6. 尝试不同的浏览器
- Chrome/Edge 最新版本（推荐）
- Firefox 最新版本
- 避免使用IE浏览器

#### 7. 检查用户权限
确认当前登录用户有相应的权限：
- `line.read` 或 `line.manage` 权限

### 临时调试方法

如果以上方法都不行，可以在浏览器控制台手动测试导出功能：

```javascript
// 测试PDF导出
const detail = {
  fault_id: "TEST-001",
  line_name: "测试线路",
  station: "测试厂站",
  fault_datetime: "2026-07-04 10:00:00"
};

// 检查函数是否存在
console.log('exportToPDF:', typeof exportToPDF);
console.log('exportToWord:', typeof exportToWord);
```

### 常见原因及解决方案

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 按钮没有下拉菜单 | 代码未生效 | 强制刷新浏览器 |
| 点击后无反应 | JavaScript错误 | 查看控制台错误 |
| 下载没开始 | 浏览器阻止下载 | 允许浏览器弹窗和下载 |
| 导出失败提示 | 数据格式错误 | 检查控制台详细错误信息 |

### 如果问题依然存在

请提供以下信息：

1. **浏览器版本**：Chrome/Edge/Firefox + 版本号
2. **控制台错误信息**：完整的红色错误文本（截图）
3. **网络请求状态**：是否有失败的请求
4. **操作系统**：Windows/Mac/Linux
5. **是否能看到下拉菜单**：点击"导出报告"是否显示下拉选项

### 开发服务器信息

- 本地地址: http://localhost:3001
- 网络地址: http://10.19.196.20:3001
- 生产地址: http://223.109.142.84:3002

### 紧急备用方案

如果导出功能始终无法使用，可以使用以下备用方案：

1. **浏览器打印为PDF**
   - 在详情页面按 `Ctrl + P`（或 `Cmd + P`）
   - 选择"保存为PDF"
   - 点击保存

2. **截图工具**
   - 使用浏览器扩展（如 Full Page Screen Capture）
   - 截取完整页面

3. **复制内容到Word**
   - 全选页面内容 `Ctrl + A`
   - 复制 `Ctrl + C`
   - 粘贴到Word文档
