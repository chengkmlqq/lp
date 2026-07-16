---
name: fquiz-requirement-analyze
description: 通过 JWT 链路执行“先查询后分析再写回”需求流程（login -> jwt -> requirement search/get/lifecycle -> requirement analyze）。当用户要求分析 fquiz 项目待分析/待修订需求并回写到待评审时使用。脚本只做接口调用与数据编排；需求方案必须由大模型结合真实工程代码阅读后生成。若需求涉及前端/UI/交互，分析阶段必须先调用 `ui-ux-pro-max` 输出专项评估后再回写。
---

# Quiz Requirement Analyze

## 核心原则（强制）

1. **脚本只负责接口调用**：登录、JWT、查询、详情、生命周期、analyze 回写。
2. **需求方案由大模型生成**：不得在 Python 脚本里写模板化方案生成逻辑。
3. **必须读代码再分析**：先根据需求定位并阅读相关工程代码，再输出分析内容。
4. **代码检索默认使用 `grep/find/read`**：将其作为通用检索手段；不要依赖 `rg`（环境不保证存在），除非先确认已安装。
5. `PENDING_REVISION` 必须纳入评审备注（`resultMsg` + 最新 `lifecycle.REVIEW.remark`）后再回写。
6. **涉及前端/UI/交互的需求必须先调用 `ui-ux-pro-max`**：先输出 UI/UX 评估与改造建议（至少含 P0/P1/P2），再合并进最终 `descr` 回写。

---

## 执行流程（推荐）

### A. 拉取需求数据（脚本）

```bash
python3 skills/fquiz-requirement-analyze/scripts/analyze_requirement.py \
  --action query \
  --project-name fquiz \
  --status PENDING_ANALYSIS,PENDING_REVISION \
  --with-review-remark
```

必要时读取单条详情/生命周期：

```bash
python3 skills/fquiz-requirement-analyze/scripts/analyze_requirement.py \
  --action get \
  --requirement-id <REQ_ID> \
  --with-lifecycle
```

### B. 代码定位与阅读（大模型必须执行）

按需求主题在工程中检索并阅读真实代码（前端页面、API 调用、后端 controller/service/repository、权限判断、DTO 字段）。
优先使用 `grep/find/read` 完成检索与阅读（兼容性更高），避免把 `rg` 作为前置依赖。

最低要求：
- 给出**具体文件路径**（必要时函数/代码块）
- 说明**现在是怎么实现的**
- 说明**要改哪里、怎么改**
- 说明**影响范围与风险**

> 禁止只给固定“定位链路模板”而不读实际代码。

### C. UI/UX 专项评估（涉及前端时强制）

当需求描述或代码范围涉及页面/交互/样式/可视化（如 `web/src/**`、页面布局、表单、列表、导航、弹窗、状态反馈、响应式、可访问性）时：

1. 必须先调用 `ui-ux-pro-max` 技能输出专项评估。
2. 评估结果至少包含：
   - 执行摘要（3-5 条）
   - P0 / P1 / P2 改造建议
   - 每条建议的现状、影响、改法、建议改动位置（文件/模块）
3. 将 UI/UX 结论合并到最终 `descr`（不可只单独附链接或一句话带过）。

### D. 生成并回写分析（脚本仅回写）

把大模型生成的分析文本作为 `descr` 回写。

> 推荐优先使用 `--descr-file`（避免超长命令/复杂 here-doc 被执行器 preflight 拦截）。

方式 1（推荐，文件入参）：

```bash
python3 skills/fquiz-requirement-analyze/scripts/analyze_requirement.py \
  --action analyze \
  --requirement-id <REQ_ID> \
  --descr-file /tmp/requirement-analyze-descr.txt
```

方式 2（短文本可用，直接传参）：

```bash
python3 skills/fquiz-requirement-analyze/scripts/analyze_requirement.py \
  --action analyze \
  --requirement-id <REQ_ID> \
  --descr "<模型生成的分析文本>"
```

批量回写（建议）：准备 JSON 数组文件（每项含 `requirementId`,`descr`，可选 `progressPercent`）后执行：

```bash
python3 skills/fquiz-requirement-analyze/scripts/analyze_requirement.py \
  --action batch-analyze \
  --batch-file /tmp/requirement-analyze-items.json
```

---

## 分析内容规范（由大模型生成）

### 简单 bug / 小需求

`descr` 保持简洁，至少包含：
1. 代码位置
2. 怎么改（最小改动）
3. 影响范围

### 复杂功能

可输出详细方案，至少包含：
1. 目标与现状
2. 代码定位与当前实现
3. 方案与步骤
4. 影响/风险/回滚
5. 验收点

### 涉及前端/UI 需求（新增强制项）

除上述要求外，必须追加：
1. `ui-ux-pro-max` 评估摘要（3-5 条）
2. P0 / P1 / P2 UI/UX 改造建议（每条含现状、影响、改法、建议位置）
3. 至少 3 条可快速落地的 UI quick wins

---

## 脚本参数（接口适配）

脚本：`scripts/analyze_requirement.py`

### 通用
- `--action`：`query|get|lifecycle|analyze|batch-analyze`（必填）
- `--base-url` / `--user-id` / `--user-pwd` / `--timeout`

### query
- `--project-name`（默认 `fquiz`）
- `--status`（可重复或逗号分隔，默认 `PENDING_ANALYSIS,PENDING_REVISION`）
- `--page-size` / `--max-items`
- `--with-review-remark`（对 `PENDING_REVISION` 补充评审备注）

### get / lifecycle
- `--requirement-id`（必填）
- `--with-lifecycle`（仅 get 时可用）

### analyze
- `--requirement-id`（必填）
- `--descr` 或 `--descr-file`（二选一，必填其一；推荐 `--descr-file`）
- `--progress-percent`（可选）

### batch-analyze
- `--batch-file` 或 `--batch-json`（二选一，JSON 数组）
- `--batch-file-encoding`（可选，默认 `utf-8`）

---

## 输出字段（关键）

- `query`：`count`、`statusCount`、`processingOrderRule`、`queryTrace`、`items[]`
- `get`：`requirement`（可选 `lifecycle`）
- `lifecycle`：`logs[]`
- `analyze`：`writebackSuccess`、`statusAfterWriteback`、`payload`
- `batch-analyze`：`total/success/failed`、`items[].writebackSuccess`

---

## 约束

- 回写分析只使用 `descr`（可选 `progressPercent`）。
- 不使用 `comment` / `analysisRemark`。
- 脚本内禁止内置“需求方案模板自动生成”。
- 分析必须基于真实代码阅读结果，不得只复述需求描述。
- 代码检索与定位默认使用 `grep/find/read`；若使用 `rg`，需先确认环境可用。
- 涉及前端页面/交互/样式的需求，分析阶段必须先调用 `ui-ux-pro-max`，并把结论合并进 `descr` 后再回写。
