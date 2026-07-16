【需求背景】
- 需求 ID：313321162778084155
- 标题：fquiz页面Ant Design组件改造：/admin/prompt
- 当前状态：PENDING_ANALYSIS（本次按“新分析”处理，非 PENDING_REVISION）

## 一、目标
将 `/admin/prompt` 页面改造为以 Ant Design 组件为主的页面实现，统一视觉与交互规范，同时保持现有业务语义与后端接口协议不变（仍使用 system-message 领域接口与权限）。

## 二、现状（基于真实代码）
### 1) 页面实际入口与复用关系
- `web/src/app/admin/prompt/page.tsx:1`：当前 `/admin/prompt` 仅 re-export `../system-message/page`。
- `web/src/app/admin/system-message/page.tsx`：实际承载提示词管理页面的完整 UI 与交互。

### 2) 现有 UI 结构与技术栈现状
- 页面虽然引入了 `@/components/ui-antd` 的包装组件（Button/Select/Table/TextField/TextArea），但仍大量依赖 Tailwind class 手工拼装布局和状态样式，组件层不够“原生 Ant Design 化”。
- 列表、筛选、表单、反馈、删除确认等能力均已具备，但实现分散：
  - 列表：`Table.Root` + 手工 `<Table.Row>` 渲染。
  - 筛选：输入框+下拉组合，缺少统一 Form 语义。
  - 反馈：错误/成功使用 `<pre>`（`web/src/app/admin/system-message/page.tsx:241-242`）且存在 className 重复拼接问题。
  - 删除确认：`window.confirm`（`337` 行附近），非 AntD 交互模式。
  - 表单：手写 state 校验（标题/内容非空），未使用 AntD Form rule。

### 3) 数据与权限链路（无需改协议）
- 前端接口：`/api/v1/admin/system-messages`（GET/POST/PATCH/DELETE）。
- 后端路由：`api/app/api/v1/system_messages.py`。
- 服务层：`api/app/services/system_message_service.py`，支持关键词/状态/等级过滤、CRUD、topic 推送 `admin.system-messages`。
- 权限：`system_message.read` / `system_message.manage`（前后端一致）。

## 三、范围（In Scope）
1. `/admin/prompt` 对应页面（实际文件为 `web/src/app/admin/system-message/page.tsx`）的组件层改造：
   - 布局容器
   - 筛选区
   - 列表区
   - 编辑/新建表单区
   - 删除确认
   - 成功/错误提示
   - 空态/加载态
2. 页面内样式与交互统一到 Ant Design 设计语言。
3. 保留既有 API 调用、权限判断、字段语义、topic 刷新机制。

## 四、非范围（Out of Scope）
1. 后端接口协议、字段定义、权限模型调整（`system_message.*` 不改）。
2. 业务语义重构（例如将 system-message 全量重命名为 prompt）。
3. 新增跨页面能力（如全局主题策略重构、后台导航体系变更）。
4. 大规模数据层改造（分页协议、搜索索引策略等）。

## 五、实现思路（建议方案）
### 阶段 1：组件骨架 AntD 化（优先）
- 将主要页面结构迁移为 AntD 组合：`Card` + `Space` + `Form` + `Table` + `Alert` + `Empty` + `Spin`。
- 目标是减少手工 class 驱动的视觉差异，保证页面在浅色/暗色/紧凑主题下表现一致。

### 阶段 2：交互链路标准化
- 删除确认改为 `Popconfirm`（替换 `window.confirm`）。
- 成功/失败反馈改为 `Alert`（常驻）+ `message`（短反馈）组合。
- 列表状态字段使用 `Tag` 显示（level/status 颜色映射），增强信息辨识度。

### 阶段 3：表单体验与可用性增强
- 改为 AntD `Form` 驱动校验（title/content 必填、时间区间合法性前置校验）。
- 时间输入优先 `DatePicker`（必要时 `showTime`），并统一转换为 UTC ISO 后提交（保持后端兼容）。

### 阶段 4：稳态验证
- 保持 React Query key、invalidate 策略、topic 订阅机制不变。
- 做关键路径回归：筛选→编辑→保存→刷新、创建→发布、删除→刷新。

## 六、影响点
### 前端影响
- 主要改动文件：
  - `web/src/app/admin/system-message/page.tsx`（核心）
  - `web/src/app/admin/prompt/page.tsx`（保留 re-export，可不动）
- 可能涉及：
  - `@/components/ui-antd` 是否继续封装复用，或页面直接使用 `antd` 原生组件。

### 后端影响
- 无接口协议变更。
- 仅受前端请求时机变化影响（例如校验前置后无效请求会减少）。

### 用户与运营影响
- 页面风格更统一，操作路径一致性提升。
- 学习成本下降（更贴近后台其他 AntD 页面操作习惯）。

## 七、UI/UX 专项评估（按 ui-ux-pro-max 要求）
### 执行摘要（5 条）
1. 页面已具备完整业务能力，但交互组件呈“混合态”（包装组件 + 手工样式 + 浏览器原生交互），一致性不足。
2. 删除确认、状态反馈、空态加载表现不够 AntD 化，影响专业感与可预期性。
3. 表单缺少系统化校验/错误提示结构，用户修复输入错误路径不够清晰。
4. 列表信息层级（等级/状态）可视化弱，扫描效率偏低。
5. 通过 P0/P1/P2 分层改造可低风险推进，且不触碰后端协议。

### P0（必须优先）
1) 反馈与错误展示标准化
- 现状：错误/成功均用 `<pre>`，且 class 重复拼接。
- 影响：可读性差，视觉不统一；可维护性低。
- 改法：改为 `Alert`（error/success），并在提交动作配合 `message.success/error`。
- 建议位置：`web/src/app/admin/system-message/page.tsx` 顶部反馈区（约 239-243 行）。

2) 删除交互规范化
- 现状：`window.confirm`。
- 影响：样式割裂，不利于统一交互预期。
- 改法：使用 `Popconfirm` 包裹删除按钮，统一文案与危险操作语义。
- 建议位置：列表操作列（约 333-341 行）。

3) 表单校验改为 Form 规则
- 现状：仅在 mutation 前手写非空校验。
- 影响：错误提示触达滞后，字段级反馈不足。
- 改法：使用 `Form` + `rules` + 字段级错误提示，并保留后端兜底。
- 建议位置：编辑区（约 362-444 行）。

### P1（高价值）
1) 列表信息视觉层级增强
- 现状：level/status 文本裸露展示。
- 影响：高密度列表下可扫读性弱。
- 改法：引入 `Tag` 映射颜色（info/success/warning/error；draft/published/archived）。
- 建议位置：表格列渲染（约 321-323 行）。

2) 空态/加载态 AntD 化
- 现状：加载使用纯文本；空态通过“无数据行文本”。
- 影响：状态感知弱，体验不一致。
- 改法：列表加载使用 `Spin`/`Skeleton`，空态使用 `Empty`。
- 建议位置：`initializing/listQuery.isLoading` 分支 + Table 空数据分支。

3) 筛选区表单化
- 现状：筛选控件裸排版，缺少统一字段语义。
- 影响：拓展筛选项时可维护性下降。
- 改法：`Form layout="vertical"` + `Input`/`Select` + 统一重置行为。
- 建议位置：筛选区（约 255-296 行）。

### P2（优化项）
1) 时间输入体验优化
- 现状：`datetime-local` 依赖浏览器原生控件。
- 影响：跨端体验差异较大。
- 改法：`DatePicker showTime`，统一展示与选择体验。
- 建议位置：生效/失效时间字段（约 413-429 行）。

2) 文案语义一致性
- 现状：菜单写“提示词管理”，页面主体仍“系统消息”。
- 影响：用户心智略有割裂。
- 改法：确认产品术语后统一页面标题/提示文案（仅文案层，不改 API 语义）。
- 建议位置：标题、副标题、成功提示文案。

3) 移动端操作区紧凑优化
- 现状：操作按钮横向排列，窄屏可能拥挤。
- 影响：可点性与阅读体验下降。
- 改法：`Space` + 响应式折叠（必要时 Dropdown）。
- 建议位置：操作列按钮容器（约 331-345 行）。

### 可快速落地的 UI Quick Wins（至少 3 条）
1. 用 `Popconfirm` 替换 `window.confirm`（半天内可完成，风险低）。
2. 将反馈 `<pre>` 改为 `Alert` + `message`（半天内可完成）。
3. level/status 增加 `Tag` 颜色映射（半天内可完成）。
4. 空态改 `Empty`、加载态加 `Spin`（半天内可完成）。

## 八、风险 / 疑问
1. 术语风险：页面是“提示词管理”还是“系统消息管理”需产品确认（当前前后端均是 system-message 语义）。
2. 时间处理风险：从 `datetime-local` 迁移到 `DatePicker` 后，需明确时区展示与提交策略（建议继续提交 UTC ISO）。
3. 封装策略风险：是否继续统一使用 `ui-antd` 封装，还是在此页直接使用 antd 原生组件，需要团队统一。
4. 数据量风险：当前列表无分页，若后续数据增长，纯前端全量渲染性能可能下降（本需求先不改协议）。

## 九、建议验收标准
1. **功能等价**：筛选、创建、编辑、删除、实时刷新（topic）均与现状一致，不出现回归。
2. **组件达标**：页面核心交互组件（筛选、表格、表单、反馈、确认、空态/加载态）采用 Ant Design 体系实现。
3. **视觉一致**：在浅色/暗色/紧凑主题下无明显样式断层；危险操作、状态提示、字段校验风格统一。
4. **交互可用**：关键路径（创建->发布->编辑->删除）可用，错误提示清晰、字段级校验可见。
5. **接口不变**：后端 API 路径、请求/响应字段、权限码保持不变。
6. **回归通过**：
   - 有权限账号可完整操作；
   - 仅 `system_message.read` 账号只读；
   - 无权限账号看到正确拦截文案。

## 十、结论
该需求可在不改后端协议与业务语义前提下完成。建议采用“P0（反馈/确认/校验）-> P1（信息层级/状态体验）-> P2（输入体验与文案一致性）”的增量改造策略，优先交付低风险高收益项。