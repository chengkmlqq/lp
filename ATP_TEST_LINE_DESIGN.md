# ATP 测试线路（单塔基准）改造方案

> 目标：把「ATP 模型测试」的输入从**手工填两个 JSON / 手工挑一根真实线路杆塔**，改造成
> **按维度组合配置一条受控的单杆塔测试线路**，并让测试集以测试线路为基准批量生成与回归。
>
> 文档版本：v1（2026-11-01）｜状态：待评审

---

## 1. 现状与真实痛点

### 1.1 单模型测试的输入现状

`AtpAssetTestRunRequest`（`api/app/schemas/atp_asset.py:204-235`）有三种参数来源：

| 来源 | 触发方式 | 问题 |
|---|---|---|
| `params_source="template"` | 默认 | 无杆塔，几何靠参数模板 `defaults_json` **合成**（`atp_asset_test_service.py:539-643`）；缺 `lw_l_eff/sp_u…` 直接抛错 |
| `params_source="tower"` + 手填 `base_tower`/`profile` | 前端 TextArea 手填 JSON | 20+ 个工程字段手填，无校验、无预览（`atp-test-run-modal.tsx:371-388`） |
| `line_tower_id` | 从真实线路里挑 **1 基**杆塔（`atp-test-run-modal.tsx:179` 取 `[0]`） | 依赖外业台账；同一维度组挑不同塔，结果不可比 |

`base_tower` / `profile` 的字段全集（`fl_analysis_service.py:2749-2776` / `2879-2918`）：
档距 `span_small_m/span_large_m`、接地电阻、地闪密度、海拔、地形、`slope_1/2`、呼高、绝缘子串长、
避雷线高度与左右中距、保护角、相序、避雷器 A/B/C、回路几何（`tower_circuit` 上/中/下相中距与相高）……

**结论：这套参数本质上就是「一基杆塔 + 一档线路」的完整物理描述，系统里却没有任何一等实体承载它。**

### 1.2 测试集现状

- 用例 = `asset_id` + `job_kind` + 一坨 `params_json`（`models/atp_test_set.py:71-109`），**只能逐条手工建**
  （`atp-test-set-detail-drawer.tsx:788-863`），没有批量生成、没有模板、没有按维度展开。
- 用例 `params_json` 直接 `model_validate` 成测试请求（`atp_test_set_service.py:323-335`）——黑盒 JSON，
  没有 schema 校验、没有默认值收敛，两个人建同一维度组的用例参数大概率不一致。
- 用例**没有** `line_tower_id` 字段 → 测试集无法绑定任何线路/杆塔，只能靠 JSON 里塞 `base_tower`。

### 1.3 四个会让这个需求"落空"的底层缺口（必须在同批次修）

| # | 缺口 | 证据 | 后果 |
|---|---|---|---|
| **a** | 参数模板的维度匹配 context 里**没有** `scene_type` / `arrester_config` / `structure_kind` | `atp_param_resolver.py:614-663`（context 只填 `voltage_level`/`tower_type`/`circuit_count`/几何量）；`DIMENSION_KEYS` 却声明了 6 个 | "按场景/避雷器组合配置"在参数层面**完全不生效**——规则永远匹配不上，只能靠换模型文件 |
| **b** | `slope_1/slope_2` / `terrain` / `altitude_m` **无任何消费方** | `atp_geometry_pipeline.py`、`fl_analysis_external.py:459-940` 全文无引用；只在 `_build_base_tower_json` 里被搬运 | 场景（山地/平地、倾角）不影响几何，测试线路的"地形"字段是死数据 |
| **c** | 任务结束**无条件删除** `run_dir`，而 `compare.json`/`artifacts.zip` 就在里面 | `atp_asset_test_service.py:464-468` + `:1440-1447`（docstring 与实现相反）；产物接口因此走 404 分支 | 测试集回归报告拿不到逐用例产物；基准不可追溯 |
| **d** | `dimension_item` 只有 `code/name/description/sort_order`，**没有工程属性载体** | `models/dimension_item.py:17-59` | "基于系统里配置的维度数据生成测试线路"没有数据来源——电压等级选 500kV 也拿不到"绝缘子串长该填多少" |

> 另有一个运维事实：ATP 测试走 `wine` 队列，本机（111.170.33.2）**没有 wine 消费者**，
> 实际消费者是 `wine_worker@lp`（flower 可见，`max-concurrency=1`，串行）。
> 批量测试的吞吐上限 = 1，方案里的并发假设必须按串行设计。

---

## 2. 核心判断：新建「测试线路」实体，不复用真实线路

| 维度 | 复用 `power_line` + `power_line_tower` | 新建 `atp_test_line`（推荐） |
|---|---|---|
| 数据语义 | 外业台账，随实测资料持续更新 | 回归基准，必须**可冻结、可复现** |
| 出现在业务列表 | 会污染线路管理/地图/统计 | 独立命名空间 |
| 维护方式 | 只能 CSV/Excel 导入 63 列 | 表单编辑 + 从资产/塔型号派生 |
| 维度绑定 | 塔型靠 `tower_type` 字符串，无维度约束 | 与 `atp_asset` 同构的维度键，可直接匹配 |
| 版本/状态 | 无 | `status` + `snapshot_json` 冻结 + 变更留痕 |
| 改造成本 | 0（直接复用现有 `line_tower_id` 链路） | 新表 + 装配器抽取，但链路复用同一出口 |

**结论：新表承载数据，但复用同一份装配代码**——把 `_build_base_tower_json` / `_build_profile_json`
抽成 `atp_line_snapshot.py` 公共装配器，真实杆塔与测试线路都走它输出 `base_tower`/`profile`，
保证两条路径**口径完全一致**（否则测试基准和生产线结果不可比）。

---

## 3. 概念模型

```
维度组合（与 atp_asset 同构）
  ├─ 几何维：voltage_level × tower_type × shield_wire   ← 决定杆塔几何，唯一键
  └─ 标签维：scene_type × arrester_config               ← 不改变几何，只用于模型选择/参数规则
                │
                ▼
        atp_test_line（单塔基准，含 snapshot_json 冻结）
                │ 1:N
                ▼
      atp_test_line_circuit（I~IV 回相中距/相高）
                │
                ├──▶ atp_asset.test_line_id（模型级绑定，可选，优先）
                └──▶ atp_test_set_case.test_line_id（用例级绑定）
```

**三级解析（`resolve_test_line`）**

1. **模型级绑定**：`atp_asset.test_line_id` 直接命中（给"这个模型必须用专用样本"的场景）
2. **几何维匹配**：`(voltage_level, tower_type, shield_wire)` + `status=enabled` + `asset_id IS NULL`
   （共享基准；同一维度组的多版本资产共用一条）
3. **降级匹配**：仅 `(voltage_level, tower_type)` 命中且唯一 → 记 `degraded=true` 并写入 compare.json
4. **无命中 → 409**，返回可执行的补救指令（`POST /test-lines:derive`），**不静默降级到 template 模式**
   （对齐现有"缺数据必须显式报错"的原则，`atp_asset_test_service.py:567-571`）

> **为什么不是"每种场景一条"**：场景 `fanji/raoji1/2/3` 在 ATP 侧体现为**不同的模型文件**（电路结构不同），
> 不改变杆塔几何；避雷器组合同理（埋在不同 work.atp 里），也不改几何。
> 若按 9 电压 × 9 塔型 × 2 避雷线 × 4 场景 × 9 避雷器 = **5832 条**，维护不可行。
> 因此：**几何按 3 维建（上限 162 条），场景/避雷器通过"选哪个资产 + 参数规则"体现**；
> 确有专用样本需求的模型，用 `atp_asset.test_line_id` 单独绑一条。此点见 §14 决策点 1。

---

## 4. 数据模型

### 4.1 新表 `atp_test_line`（测试线路 / 单塔基准）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `code` / `name` / `description` | String(32/64/255)/Text | `code` 唯一，建议 `TL-{电压}-{塔型}-{避雷线}` |
| `status` | String(20) | enabled / disabled / **frozen**（冻结后禁止自动重派生） |
| **维度键** | | |
| `voltage_level` | String(16) | 维度码，如 `500` |
| `tower_type` | String(64) | 塔型**基名**（`guxing`/`maotou`…），需归一化后存 |
| `shield_wire` | String(16) | with / without（默认 with） |
| `scene_type` | String(32) | 标签维（如 `fanji`），不参与唯一键 |
| `arrester_config` | String(64) | 标签维（如 `M123`），不参与唯一键 |
| `structure_kind` | String(20) | 直线 / 耐张 |
| `circuit_count` | Integer | 1~4，由回路几何推导，落库便于筛选 |
| **绑定** | | |
| `asset_id` | String(32) NULL | 模型级专用样本（NULL = 维度组共享） |
| **线路环境** | | |
| `span_small_m` / `span_large_m` | Float | → `xiaohao.dat` / `dahao.dat` 频率卡（`atp_geometry_pipeline.py:230-241`） |
| `ground_resistance_ohm` | Float | → 参数规则 `ground_r` |
| `lightning_density` | Float | 地闪密度 |
| `altitude_m` | Float | 海拔（当前无消费方，见 §8-b） |
| `terrain` | String(64) | 地形（同上） |
| `slope_1` / `slope_2` | Float | 地面倾角（同上） |
| **杆塔属性** | | |
| `tower_no` | String(64) | 渲染占位符用 |
| `call_height_m` | Float | 呼高 |
| `insulator_length_m` | Float | 绝缘子串长（**注意代码里按 mm 存、内部 /1000**，`atp_geometry_pipeline.py:100-105`） |
| `shield_wire_height_m` | Float | 避雷线高度 |
| `shield_wire_left_mid_m` / `shield_wire_right_mid_m` | Float | 避雷线左右中距（缺则几何直接 raise） |
| `protection_angle_left_deg` / `_right_deg` | Float | 保护角 |
| `angle_deg` | Float | 电角度 |
| `phase_sequence_1..4` | String(8) | 相序（A/B/C 组合） |
| `arrester_a` / `arrester_b` / `arrester_c` | Boolean | 避雷器安装（由 `arrester_config` 规则推导，可手改） |
| **雷电流** | | |
| `current_ka` | Float | 默认测试电流（默认 31.0，与现有一致） |
| `current_type` / `current_head_time_us` / `current_tail_time_us` | Integer/Float | 波形 |
| **溯源与冻结** | | |
| `source_kind` | String(20) | derived / manual / from_tower / from_asset_run |
| `source_asset_id` / `source_run_id` / `source_tower_id` | String(32) NULL | 派生来源 |
| `derive_rules_json` | JSON | 每个字段的来源标注（模板规则/资产快照/塔型默认/内置兜底/人工） |
| `snapshot_json` | JSON | **完整冻结的 `base_tower` + `profile`**（执行时优先用它，保证可复现） |
| `snapshot_hash` | String(64) | 快照 sha256，测试集回归对比用 |
| `used_count` / `last_used_at` | Integer/DateTime | 引用统计 |
| 审计列 | | create/update_date, create/update_user |

唯一约束：`uq_atp_test_line_key (voltage_level, tower_type, shield_wire, asset_id)`
索引：`(voltage_level, tower_type, shield_wire)`、`asset_id`、`status`。

### 4.2 新表 `atp_test_line_circuit`（回路几何，1:N ≤ 4）

`test_line_id`(FK CASCADE)、`circuit_no`(1..4)、`phase_sequence`、
`spacing_upper_m`/`spacing_middle_m`/`spacing_lower_m`、
`height_upper_m`/`height_middle_m`/`height_lower_m`；唯一 `(test_line_id, circuit_no)`。

> 四回塔必须 4 套独立几何——否则 LCC 判导体重合不产 `.pch`
> （`atp_asset_test_service.py:600-620` 已有同类踩坑注释）。

### 4.3 对既有表的改动（全部 nullable，向后兼容）

| 表 | 变更 | 用途 |
|---|---|---|
| `atp_asset` | `+ test_line_id VARCHAR(32) NULL` | 模型级绑定测试线路（优先命中） |
| `atp_test_set_case` | `+ test_line_id VARCHAR(32) NULL` | 用例绑定测试线路 |
| `atp_test_set_case` | `+ test_line_snapshot_hash VARCHAR(64) NULL` | 生成时快照指纹，用于"基准已变更"告警 |
| `dimension_item` | `+ extra_json JSON NOT NULL DEFAULT '{}'` | **让维度携带工程默认值**（见 §5 第 3 级来源） |

`dimension_item.extra_json` 约定（按维度类型）：

```jsonc
// voltage_level 项：{"insulator_length_mm": 4450, "phase_spacing_default": {"upper": 12.0, "middle": 12.0, "lower": 12.0}}
// tower_type 项：{"circuit_count": 2, "call_height_m": 45.0, "geometry_layers": ["I","II"]}
// scenario 项：{"stroke_mode": "raoji", "slope_default": 10.0}
// arrester_combination 项：{"arrester": {"a": true, "b": true, "c": true}}
```

### 4.4 迁移脚本

- `api/migrations/029_add_atp_test_line.sql`（PostgreSQL 版）
- `api/migrations/mysql/030_add_atp_test_line.sql`（MySQL 版，生产用）
- 均 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN`，幂等可重跑（对齐 `028` 风格）

---

## 5. 参数从哪来：派生（derive）规则

新建/重派生时按 **4 级来源**逐字段填充，每字段记录来源：

| 级别 | 来源 | 取什么 | 可信度 |
|---|---|---|---|
| L1 | **该资产最近一次成功 run 的 `compare.json`** | `case.base_tower` / `case.profile` 全量（真实跑通过的参数） | 最高 |
| L2 | `atp_param_template.defaults_json`（按维度匹配） | `h_u/sp_u/insul_m/shield_h/lw_l/lw_r/ground_r`… 无杆塔模式下的合成默认值 | 高 |
| L3 | `tower_model` 字典（按 `tower_type` + 电压匹配） | `default_span_small_m/large_m`、`default_ground_resistance_ohm`、`default_altitude_m`、`default_terrain`、`default_slope_1/2` | 中 |
| L4 | `dimension_item.extra_json`（新增） | 绝缘子串长、默认相间距、回路数、避雷器组合→A/B/C、场景→绕击模式 | 中 |
| L5 | 内置兜底表 | 电压分档的相间距/绝缘子参考值 | 低（必须标注"兜底"，UI 黄色提示） |

**派生 = 干跑预检（dry-run preflight），不落库**：

```
POST /api/v1/atp/test-lines:derive
{ asset_id?  |  voltage_level + tower_type + shield_wire }
→ {
    draft: { ...全部字段, 每个字段带 _source: "L1:run_xxx" | "L3:tower_model" | ... },
    blockers: [ {field, reason} ],       // 缺必填、几何冲突等，不可落库
    warnings: [ {field, reason} ],       // 用了兜底值、四回几何缺失等
  }
```

**必须校验的几何约束**（否则 LCC 直接失败或结果失真）：

1. `insulator_length_m` 单位一致性（mm 入库 / m 计算，二选一并在 UI 明确标注）
2. 避雷线左右中距必须 > 0（缺失即 `RuntimeError`，`atp_asset_test_service.py:567-571`）
3. 四回塔的 II/III/IV 回几何不得与 I 回完全重合（否则 LCC 不产 `.pch`）
4. `span_small_m` / `span_large_m` 落在 `(0, 3000]` 米
5. `tower_type` 归一化后必须能在资产/塔型字典中命中（`fl_analysis_external.py:411-429` 的
   `_normalize_tower_shape_code` 会把 `d500guxing` → `guxing`），归一化不一致时给出提示

---

## 6. 执行链路改造

### 6.1 请求优先级

`AtpAssetTestRunRequest` 新增 `test_line_id: str | None`。优先级（互斥，冲突报 400）：

```
test_line_id  >  line_tower_id  >  显式 base_tower/profile  >  params_source="template"
```

### 6.2 worker 侧（`execute_test_run_job`，`atp_asset_test_service.py:292-470`）

在现有 `line_tower_id` 分支（`:307-334`）旁增加：

```python
elif payload.test_line_id:
    tl = resolve_test_line(db, payload.test_line_id)          # 404 / disabled 校验
    base_tower, profile = assemble_from_test_line(tl)         # 与 tower 路径共用装配器
    payload.base_tower = base_tower
    payload.profile = profile
    payload.params_source = "tower"                            # 复用既有几何/参数通道
    payload.tower_kind = tl.tower_type                         # 已归一化
    payload.voltage_kv = int(tl.voltage_level)
    event_meta["test_line"] = {"id": tl.id, "code": tl.code, "snapshot_hash": tl.snapshot_hash}
```

- 若 `test_line_id` 为空，则用 §3 的三级解析**反查**一条（`params_source` 仍是 template 时也先尝试反查，
  命中则升为 tower 模式并记 `auto_resolved=true`）——这是"模型测试默认就用测试线路"的落点。
- `compare.json` 增加 `case.test_line` 段（id/code/snapshot_hash/derive_rules），与 C# 对拍的 `params_raw` 并列。

### 6.3 装配器抽取

新增 `api/app/services/atp_line_snapshot.py`：

```python
def build_base_tower(tower_like) -> dict[str, Any]     # ← 从 fl_analysis_service._build_base_tower_json 平移
def build_profile(tower_like) -> dict[str, Any]        # ← 从 _build_profile_json 平移（含 geometry_layers_json 合并）
def snapshot_from_test_line(tl) -> tuple[dict, dict]   # 测试线路 → (base_tower, profile)
def snapshot_from_line_tower(tower, line) -> tuple[dict, dict]  # 真实杆塔 → 同上
```

要求：`snapshot_from_*` 两者输出**字段集完全一致**，用单测断言 key 集合相等（防止两条路径漂移）。

---

## 7. 测试集改造

### 7.1 用例结构

`atp_test_set_case` 增 `test_line_id`。执行时 payload 构造（`atp_test_set_service.py:323-335`）改为：

```python
params = dict(case.params_json or {})
if case.test_line_id:
    params["test_line_id"] = case.test_line_id   # 优先级高于 params_json 里的 base_tower/profile
```

保留 `params_json` 用于覆盖个别参数（如 `current_ka`、`stages`），**不再承载几何**。

### 7.2 按维度矩阵批量生成

```
POST /api/v1/atp/test-sets/{id}/cases:generate
{
  voltage_levels: ["500","220"],
  tower_types: ["guxing","maotou"],
  shield_wire: ["with"],
  scene_types: ["fanji","raoji1"],
  arrester_configs: ["M123"],
  job_kinds: ["normal","tongtiao"],
  only_with_asset: true,           // 默认 true：只为本维度组存在生效(is_active)资产的组合生成
  auto_create_test_line: true,     // 缺失测试线路时按 §5 派生并落库（干跑可关）
  dry_run: true                    // 先预演，返回清单供确认
}
→ {
  planned:  [{combo, asset_id, asset_code, test_line_id?, action}],
  skipped:  [{combo, reason: "无生效资产" | "无可用测试线路" | "用例已存在"}],
  summary:  {total, create, reuse, skip}
}
```

- 去重键：`(set_id, asset_id, test_line_id, job_kind)`
- 生成后 `sort_order` 按 `电压 → 塔型 → 场景 → 避雷器 → job_kind` 排序，保证报告可读
- 组合数上限保护（默认 ≤ 200 条/次，超出要求分批）

### 7.3 回归口径

- 用例首次执行记录 `baseline_run_id`（集合级），后续每次执行与它比；
  现有 `_build_regression`（`atp_test_set_service.py:701-760`）逻辑不动
- 新增「基准漂移」告警：用例的 `test_line_snapshot_hash` 与当前测试线路快照 hash 不一致时，
  报告里标注"基准已变更，回归结论不可直接比"

---

## 8. 必须同批修复的底层缺口

### a) 维度注入参数模板 context（必做，改动最小收益最大）

`atp_param_resolver.build_context`（`:614-663`）补：

```python
for key in ("scene_type", "arrester_config", "structure_kind"):
    if options.get(key) not in (None, ""):
        context[key] = options[key]
```

配套：`atp_asset_test_service` 里把 `asset.scene_type` / `asset.arrester_config` / `profile.structure_kind`
一并塞进 `execution_options`（现在只 setdefault 了 `scene_type`，`:726`）。
否则"按场景/避雷器配置参数规则"这条能力等于不存在。

### b) 地形/倾角：先声明边界，再谈注入

- **P0**：测试线路里保留 `terrain/slope_1/slope_2/altitude_m` 字段并在 UI 展示，
  但在 `compare.json` 里明确标注 `not_consumed: true`（诚实标注，不假装生效）
- **P1**：若 `.dat` 存在地面倾角槽位，则在 `build_dat_values` 增加 `slope` 注入；
  若不存在，则改为"场景 → 参数规则里的 `slope` 变量"，由参数模板消费
- **不建议**在没有确认 C# 口径前擅自定义倾角进几何（会造成与生产线结果不可比）

### c) 产物留档（测试集回归的前提）

`execute_test_run_job` 第 ⑩ 步（`:464-468`）改为：

```
归档 compare.json / artifacts.zip → <atp_engine_workdir>/archive/<batch_id 或 asset_id>/<run_id>/
再删除 run_dir
```

- 单模型测试：仍可保留"不归档"选项（默认归档，磁盘占用可控——单个 compare.json 几十 KB，
  artifacts.zip 主要含 .lib/.dat/.lis，单次 < 2 MB）
- 磁盘保护：归档目录按 `batch_id` 保留最近 N 次（默认 10），超出滚动删除
- 顺带修 `cleanup_test_run_dir` 的 docstring 与实现相反问题（`:1440-1447`）

### d) 维度项承载工程属性（"基于维度配置"的落点）

- `dimension_item.extra_json` + 维度管理页「工程默认值」折叠面板（按类型渲染不同表单片段）
- 后端 `dimension_service` 增加 `extra_json` 透传与按类型 schema 校验
- 未配置时回落 L5 内置兜底并标注——**不允许因为维度缺配置而生成跑不通的测试线路**

---

## 9. API 清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/atp/test-lines` | 列表（筛 `voltage_level/tower_type/shield_wire/status/keyword`，分页） |
| POST | `/api/v1/atp/test-lines` | 新建（带 circuits 子表） |
| GET | `/api/v1/atp/test-lines/{id}` | 详情（含 snapshot 与 derive_rules） |
| PATCH | `/api/v1/atp/test-lines/{id}` | 编辑（改后自动重算 snapshot，`status=frozen` 时禁止） |
| DELETE | `/api/v1/atp/test-lines/{id}` | 删除（被资产/用例引用时 409 并列出引用方） |
| POST | `/api/v1/atp/test-lines/{id}/preview` | 装配预览：返回 base_tower/profile + 将写入的 `.dat` 关键值 |
| POST | `/api/v1/atp/test-lines:derive` | 按维度/资产派生草稿（干跑，返回来源标注） |
| POST | `/api/v1/atp/test-lines/{id}/clone` | 复制为同几何维新样本（改电压/塔型时用） |
| GET | `/api/v1/atp/test-lines/{id}/usage` | 被哪些资产/用例引用 |
| POST | `/api/v1/atp/test-sets/{id}/cases:generate` | 矩阵批量生成用例（dry_run 支持） |
| POST | `/api/v1/atp/assets/{id}/test-runs` | 既有；payload 增 `test_line_id` |

权限：读 `atp.read`，写 `atp.manage`，执行 `atp.run`（与现有一致）。

---

## 10. 前端改造

### 10.1 新增「测试线路」页（`/admin/atp-test-lines`）

- 列表：电压 / 塔型 / 避雷线 / 场景 / 避雷器 / 回路数 / 档距 / 状态 / 引用数 / 更新时间
- 左侧筛选树与 ATP 模型页同构（但只有 3 层：电压 → 塔型 → 避雷线）
- 操作：派生新建、编辑、复制、预览、删除
- 编辑抽屉 4 组：`维度信息` / `杆塔几何`（含回路几何表格）/ `线路环境` / `测试参数`，
  每个字段右侧显示来源 Tag（派生/手填/兜底），兜底值黄色标记

### 10.2 模型测试弹窗（`atp-test-run-modal.tsx`）

- 「参数来源」从 `template|tower` 扩展为三选：**测试线路（默认，推荐）** / 线路杆塔 / 模板默认
- 选"测试线路"时：自动按资产维度反查并选中；显示只读参数摘要卡（呼高/绝缘子/档距/避雷线中距…）
- 无匹配时：内联提示 + 「一键派生」按钮 → 直接调 `derive` 填充草稿 → 确认即落库
- 塔型/场景不再自由文本：改为维度下拉（与 §1.3-a 修复配套）

### 10.3 测试集详情（`atp-test-set-detail-drawer.tsx`）

- 新增「批量生成用例」：维度多选矩阵 → 预演清单（计划/跳过原因）→ 确认生成
- 用例表格增列「测试线路」（code，缺失时红色"未绑定"）+ 「基准漂移」标记

---

## 11. 迁移 / 灰度 / 兼容

1. **第 1 步（纯新增，零风险）**：建表 + 建 API + 页面；`atp_asset.test_line_id` 空。
2. **第 2 步（回填）**：脚本 `scripts/atp_test_line_backfill.py` —— 遍历 `atp_asset`，
   取每个维度组最近一次成功 run 的 `compare.json.case`，派生测试线路并落库（`source_kind=from_asset_run`），
   缺参的组合列成清单交人工补。
3. **第 3 步（切换默认）**：模型测试弹窗默认"测试线路"；测试集新建默认绑定。
4. **第 4 步（收口）**：老用例 `params_json` 里含 `base_tower/profile` 的，提示"建议迁移到测试线路"，
   批量转换工具可一键替换。
5. 全程不删除任何旧字段；`params_source=template` 路径保留（无资产/无测试线路时的兜底，但要显式提示）。

---

## 12. 验收标准

| 类型 | 标准 |
|---|---|
| **口径一致性（parity）** | 同一基真实杆塔 `line_tower_id` vs 由它派生的测试线路 `test_line_id`，两次 run 的 `compare.json` 中 `atp_params` 与 `lib_hashes` **逐字节相等**（这是"可替代真实杆塔"的硬门槛） |
| **确定性** | 同一测试线路重复跑 3 次，`snapshot_hash` / `atp_params` / `lib_hashes` 完全一致 |
| **维度覆盖** | 500kV 鼓型（有/无避雷线）、220kV 猫头、110kV 干字 各建 1 条并跑通（materialize+geometry+simulate 三段 ok） |
| **几何校验** | 故意把避雷线中距留空、四回几何写重 → 派生阶段即 `blockers` 拦截，不允许进入队列 |
| **批量生成** | 选定 2 电压 × 2 塔型 × 2 场景 × 1 避雷器 = 8 组合，预演清单正确、生成 8 条用例、全部可执行 |
| **回归** | 测试集跑两次（中间不改测试线路）→ 回归结论"无变化"；改测试线路后 → 出现"基准已变更"标记 |
| **不回归** | 现有用例（纯 `params_json`）执行结果与改造前一致；`tsc`/`eslint` 无新增；单测全绿 |

---

## 13. 分期

| 期 | 内容 | 交付价值 |
|---|---|---|
| **P0（最小闭环，约 4~5 天）** | `atp_test_line` + `_circuit` 表；装配器抽取；`test_line_id` 打通单模型测试；derive + 列表/编辑页；§8-a 维度注入 | 模型测试可"选测试线路"跑通，且每个维度组有基准 |
| **P1（批量与场景，约 3~4 天）** | 测试集 `test_line_id` + 矩阵生成；§8-c 产物归档；§8-d `extra_json` + 维度管理页 | 一键生成回归矩阵、报告可追溯 |
| **P2（场景几何，约 2~3 天）** | §8-b 地形/倾角注入（需先与 C# 口径对齐）；基准漂移自动重派生；模型总览按"已配测试线路"着色 | 场景差异真实进入仿真 |

---

## 14. 待确认的决策点

1. **测试线路的粒度**：按"几何维 (电压×塔型×避雷线)"建（推荐，上限 162 条），
   还是按"每种场景/每种模型各一条"（上限 5832 条，维护成本高）？
   → 推荐前者 + 模型级绑定兜底特殊样本。
2. **真实杆塔数据是否参与派生**：L1 来源用"历史 run 的真实参数"，是否也允许直接
   "从某条线路的某基杆塔派生成基准"（会更贴近现场，但基准会随台账变化）？
3. **绝缘子串长单位**：现有代码按 mm 入库、内部 /1000（`atp_geometry_pipeline.py:100-105`），
   测试线路表建议直接存 **m** 并在 UI 标注，需确认是否有下游依赖 mm。

---

## 附录：涉及文件清单

**后端新增**
`api/app/models/atp_test_line.py`、`api/app/schemas/atp_test_line.py`、
`api/app/services/atp_test_line_service.py`、`api/app/services/atp_line_snapshot.py`、
`api/app/api/v1/atp_test_lines.py`、`api/migrations/029_add_atp_test_line.sql`、
`api/migrations/mysql/030_add_atp_test_line.sql`

**后端修改**
`models/atp_asset.py`(+1 列)、`models/atp_test_set.py`(+2 列)、`models/dimension_item.py`(+1 列)、
`schemas/atp_asset.py`(+`test_line_id`)、`services/atp_asset_test_service.py`(解析+装配+归档)、
`services/atp_test_set_service.py`(用例+矩阵生成)、`services/atp_param_resolver.py`(维度注入)、
`services/fl_analysis_service.py`(装配器改调公共模块)、`services/dimension_service.py`(extra_json)、
`api/v1/router.py`(挂路由)

**前端新增**
`app/admin/atp-test-lines/page.tsx`、`components/atp-models/atp-test-line-tab.tsx`、
`components/atp-models/atp-test-line-editor.tsx`、`components/atp-models/atp-test-line-derive-modal.tsx`、
`components/atp-models/atp-test-set-generate-modal.tsx`

**前端修改**
`app/admin/atp-models/page.tsx`(入口)、`atp-test-run-modal.tsx`(来源三选)、
`atp-test-set-detail-drawer.tsx`(生成+列)、`types/auth.ts`、`types/dimension.ts`

**可清理**
`components/atp-models/atp-model-test-drawer.tsx`（32KB，全库无引用）、
`app/admin/atp-models/[id]/page.tsx`（无入口的遗留路由）
