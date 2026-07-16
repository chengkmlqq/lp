---
name: fquiz-requirement-develop
description: 通过 JWT 链路执行 fquiz 需求开发完整闭环（仅 action=full）：查询待处理需求 -> 开发执行 -> 状态流转（IN_PROGRESS 里程碑）-> COMPLETED（login -> jwt -> requirement search/get -> requirement status update）。当用户要求开发 fquiz 项目 OPEN/IN_PROGRESS 需求并闭环完成时使用。支持 auto-query 串行处理、逐条检查点输出、以及中断后的检查点续跑。
---

# Fquiz Requirement Develop

按“查询 -> 串行逐条读取 -> 先置为开发中 -> 开发过程中持续更新进度 -> 完成前通过开发门禁 -> 再置为完成”执行需求开发闭环。

服务地址与认证默认值已统一为与 `requirement-query` 一致：
- 默认 `base-url`: `https://www.quizck.cn`
- 默认账号: `openclaw`
- 默认密码: `12345678`

## 硬性执行约束

1. **仅串行执行**：`--auto-query` 模式下固定一条一条处理，禁止并行。
2. **逐条检查点回报**：每完成 1 条需求，立即输出一条 checkpoint 事件（JSON 行）。
3. **可恢复续跑**：中断后可通过检查点文件从最近完成位置恢复，不需要重新全量扫描。
4. **默认禁止脏工作区闭环**：若仓库存在未提交改动，默认直接失败；只有显式传 `--allow-dirty-worktree` 才允许继续。
5. **默认要求需求描述具备路径线索**：`descr` 中需有反引号路径（如 `frontend/src/...`、`backend/src/...`）；否则默认失败，只有显式传 `--allow-broad-change-detection` 才允许宽松匹配源码目录。

## 执行流程（必须）

1. 登录：`POST /api/user/login`
2. 生成 JWT：`POST /api/jwt/generate?userId=...`
3. 查询待处理需求：`POST /api/project/requirement/search`
   - 默认 `projectName=fquiz`
   - 默认状态：`OPEN`、`IN_PROGRESS`
4. 逐条读取需求详情：`GET /api/project/requirement/get/{id}`
   - 读取 `title / descr / status / progressPercent`
   - 基于 `descr` 形成开发执行计划
5. 开发开始即更新状态：`POST /api/project/requirement/{id}/status`
   - `status=IN_PROGRESS`
   - `progressPercent=<start-progress>`（默认 `0`）
6. **执行真实开发并在关键阶段持续更新进度**：`POST /api/project/requirement/{id}/status`
   - `status=IN_PROGRESS`
   - `progressPercent` 按里程碑更新（默认 `30,60,90`）
7. **完成前执行开发门禁（硬门禁）**
   - 默认先通过预检查：工作区必须干净、且需求描述需有可归因路径线索。
   - 必须检测到与需求相关的代码改动（优先按 `descr` 路径线索匹配）。
   - 必须通过构建/编译验证（仅构建，不做回归）。
   - 任一条件不满足：直接失败，且不得更新为 `COMPLETED`。
8. 仅当开发门禁通过时，完成时更新状态：`POST /api/project/requirement/{id}/status`
   - `status=COMPLETED`
   - `progressPercent=100`

> 查询与 JWT 调用风格与 `fquiz-requirement-analyze` 保持一致：统一 login + jwt + Bearer Token。

## 工程接口定位（以代码为准）

- Controller：`backend/src/main/java/com/ck/quiz/project/controller/RequirementController.java`
  - `POST /api/project/requirement/search`（继承 `BaseController#search`）
  - `GET /api/project/requirement/get/{id}`（继承 `BaseController#get`）
  - `POST /api/project/requirement/{id}/status`（`updateStatus`）
  - `POST /api/project/requirement/{id}/analyze`
  - `POST /api/project/requirement/{id}/review`
  - `GET /api/project/requirement/{id}/lifecycle`
- Service：`backend/src/main/java/com/ck/quiz/project/service/impl/RequirementServiceImpl.java`
  - `search`：按当前登录用户 + projectName/status 查询
  - `updateStatus`：状态更新、进度归一化（0-100）并写生命周期日志
- DTO：
  - `RequirementQueryDto`：`title/projectName/status/priority + pageNum/pageSize`
  - `RequirementDto`：`descr/resultMsg/progressPercent/status` 等

## 脚本

脚本：`scripts/develop_requirement.py`

### 参数说明

- `--action`：仅支持 `full`
  - 固定执行完整流程：`start -> progress(里程碑) -> complete`
  - 不再支持 `query/start/progress/complete` 单阶段动作
- `--auto-query`：批量模式（先查列表，再逐条执行 full）
- `--requirement-id`：单条模式需求 ID（未启用 `--auto-query` 时必填）
- `--status`：查询状态（可重复或逗号分隔），默认 `OPEN,IN_PROGRESS`
- `--project-name`：项目过滤，默认 `fquiz`
- `--max-items`：批量处理上限，默认 `20`
- `--page-size`：分页大小，默认 `50`
- `--progress-milestones`：关键进度里程碑，默认 `30,60,90`
- `--start-progress`：start 阶段进度值，默认 `0`
- `--base-url --user-id --user-pwd --timeout`：连接与认证参数
- `--build-timeout`：构建/编译命令超时秒数，默认 `600`
- `--skip-build-gate`：跳过构建/编译门禁（默认关闭；仅在明确允许时使用）
- `--allow-dirty-worktree`：允许在脏工作区执行（默认关闭，防止把历史改动误当成本需求开发证据）
- `--allow-broad-change-detection`：当需求描述缺少路径线索时，允许回退到源码目录宽松匹配（默认关闭）

### 检查点与续跑参数（新增）

- `--checkpoint-file`
  - 检查点状态文件（默认：`skills/fquiz-requirement-develop/runtime/auto-query-checkpoint.json`）
  - 每完成 1 条需求即原子覆盖写入，记录 `allIds / nextIndex / completedIds / lastCheckpoint / results`。
- `--resume`
  - 从 `--checkpoint-file` 的最近检查点续跑。
  - 续跑时会校验关键参数一致性（full/status/project/page-size/max-items/milestones/start-progress/base-url/user-id），防止错配。
- `--reset-checkpoint`
  - 明确要求重建计划并覆盖检查点（仅 auto-query）。
- 默认防误操作规则
  - 若 `checkpoint-file` 已存在，且未指定 `--resume` 或 `--reset-checkpoint`，脚本会直接失败，避免误从头重扫覆盖续跑上下文。
- `--checkpoint-log-file`
  - 检查点事件 JSONL 文件（默认 `<checkpoint-file>.events.jsonl`）。
- `--checkpoint-stream`
  - 检查点即时输出流：`stderr`（默认）或 `stdout`。

### 优先级处理规则（批量）

- `--auto-query` 批量模式下，需求处理顺序固定为：`HIGH -> MEDIUM -> LOW`。
- 同优先级内保持稳定顺序：按 `createDate`，再按 `id`。
- 输出中会返回：
  - `processingOrderRule`
  - `items[].processOrder`
  - `items[].priority`

## 检查点事件格式（每完成 1 条输出 1 条）

输出为单行 JSON，至少包含：
- `completedId`：刚完成的需求 ID
- `currentId`：当前处理需求 ID
- `remainingIds` / `remainingCount`：剩余待处理需求
- `statusWritebackResult`：本条需求状态回写结果（是否写回、每步 phase/status/progress/httpStatus、final）

示例：

```json
{
  "type": "checkpoint",
  "timestamp": "2026-03-23T14:20:31+08:00",
  "checkpointFile": ".../auto-query-checkpoint.json",
  "completedId": "REQ-1001",
  "currentId": "REQ-1001",
  "nextId": "REQ-1002",
  "remainingIds": ["REQ-1002", "REQ-1003"],
  "remainingCount": 2,
  "statusWritebackResult": {
    "updated": true,
    "updates": [
      {"phase": "start", "status": "IN_PROGRESS", "progressPercent": 0, "httpStatus": 200},
      {"phase": "progress", "status": "IN_PROGRESS", "progressPercent": 30, "httpStatus": 200},
      {"phase": "complete", "status": "COMPLETED", "progressPercent": 100, "httpStatus": 200}
    ],
    "final": {"phase": "complete", "status": "COMPLETED", "progressPercent": 100, "httpStatus": 200}
  }
}
```

## 输出结构（最终汇总 JSON）

- `mode`: `single` / `auto-query`
- `action`: 固定为 `full`
- `resumed`: 是否从检查点续跑
- `executionMode`: 固定 `serial`
- `checkpointFile` / `checkpointLogFile`（auto-query）
- `processingOrderRule`: 批量模式的优先级排序规则说明
- `queryTrace`: 查询轨迹（状态、页码、返回量）
- `items[]`: 每条需求的执行轨迹
  - `requirementId/title/initialStatus/finalStatusPlanned`
  - `priority/processOrder/createDate`
  - `developmentPlan`：基于 `descr` 的开发计划摘要
  - `developmentExecution`：真实开发执行结果（`changedFiles` + `buildResults`）
  - `transitionPlan`：计划中的状态与进度步骤
  - `trajectory[]`：每次实际状态更新记录

## 示例命令

### 1) 首次执行（批量串行 + 检查点）

```bash
python3 skills/fquiz-requirement-develop/scripts/develop_requirement.py \
  --auto-query \
  --action full \
  --status OPEN,IN_PROGRESS \
  --progress-milestones 25,50,80 \
  --max-items 5 \
  --checkpoint-file skills/fquiz-requirement-develop/runtime/fquiz-dev.ckpt.json
```

### 2) 中断后续跑（从最近检查点继续）

```bash
python3 skills/fquiz-requirement-develop/scripts/develop_requirement.py \
  --auto-query \
  --resume \
  --action full \
  --status OPEN,IN_PROGRESS \
  --progress-milestones 25,50,80 \
  --max-items 5 \
  --checkpoint-file skills/fquiz-requirement-develop/runtime/fquiz-dev.ckpt.json
```

### 3) 单条需求执行 full（完整闭环）

```bash
python3 skills/fquiz-requirement-develop/scripts/develop_requirement.py \
  --requirement-id <REQ_ID> \
  --action full
```

## 错误处理与回滚策略

- 参数校验失败（如 `start-progress>99`、里程碑超范围、非法 status；`--status` 非 `OPEN/IN_PROGRESS`）
  - 立即失败并返回 `step=validate`，不发起任何状态写入
- **预检查失败（新增）**
  - `step=develop_preflight`：工作区非净（未显式允许）或需求描述缺少路径线索（未显式允许宽松匹配）
  - 该场景下不允许进入 `COMPLETED` 闭环
- 登录/JWT/查询失败
  - 返回失败步骤与 HTTP 明细，不输出 token/cookie/password
- **开发门禁失败**
  - `step=develop`：未检测到需求相关代码改动，或构建/编译失败
  - 该场景下需求可能已先被置为 `IN_PROGRESS` 并写入部分进度；但必须禁止写成 `COMPLETED`
- 状态更新失败（单条）
  - 返回失败步骤 `update_status` + 对应请求参数，便于重试
- 批量执行中断/异常
  - 检查点保留最近完成位置；下次用 `--resume` 从 `nextIndex` 继续

回滚建议：
1. 若误完成（COMPLETED）：调用 `/{id}/status?status=IN_PROGRESS&progressPercent=<上次值>` 回退到处理中。
2. 若进度写错：重复调用 `/{id}/status?status=IN_PROGRESS&progressPercent=<正确值>` 覆盖。
3. 若需重新进入待处理：调用 `/{id}/status?status=OPEN&progressPercent=0`。

## 与需求分析 skill 的衔接

1. 先用 `fquiz-requirement-analyze` 将需求从 `PENDING_ANALYSIS/PENDING_REVISION` 推进到可开发状态（通常评审通过后到 `OPEN`）。
2. 再用本 skill 聚焦 `OPEN/IN_PROGRESS` 做开发执行和进度推进，直到 `COMPLETED`。
3. 两个 skill 共享同一 JWT 链路与需求查询接口，便于串联自动化流水线。
