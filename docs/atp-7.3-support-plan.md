# ATPDraw 7.3（`$INSERT` 形态）在 LP 上的支持方案

> 依据：2026-11-02 在 `D:\ATP`（1101 个模型）+ `C:\ATP\atpmingw`（mytpbig）上的实测。
> 本文把实验结论、LP 现状缺口、改造路线合成一份可执行的落地清单。
> 所有结论均可复现；标注「未验证」的条目尚未做实验，不应写入代码假设。

---

## 0. 结论摘要

| 结论 | 状态 |
|---|---|
| 7.3 的 work.atp 结构（TACS/BRANCH/SWITCH/SOURCE/`$INSERT`）mybig 全部认得 | ✅ 实测 |
| 唯一语法障碍是 `$PARAMETER` 段的写法（`$$` / 整数 / 中间变量），可机械规范化 | ✅ 实测 |
| 规范化后 `rc=0`、`pl4` 有波形、`ATP Finished`、无 KILL | ✅ 实测（4/8 模型） |
| 其余 4 个模型失败于结构缺陷，与参数段无关 | ✅ 实测 |
| 几何能否按塔重算 —— **这是真正的难点，不是语法问题** | ⚠️ 未解决 |
| 沿用 7.3 自带引擎是否可免去规范化 | ⚠️ 未验证 |

**一句话**：语法层 LP 现在就能支持，几何层需要做决策（见 §3.3）。

---

## 1. 测试结论

### 1.1 老模型全链路基线（对照组，4 样本）

| 样本 | 源 pl4 字节 | 改造后 pl4 字节 | KILL |
|---|---|---|---|
| 110 guxing fanji/M123 | 702457 | 702457 | 无 |
| 110 ganzi raoji1/noM | 369737 | 369737 | 无 |
| 220 jiubei fanji/M123 | 921719 | 921719 | 无 |
| 220 maotou fanji/M123 | 921827 | 921827 | 无 |

老形态 = `$INCLUDE, D:\ATP\...\long.lib, X0245A, X0245B, X0245C $$`，节点名写在 work.atp 里，
lib 内部是占位名 `IN___A`。LP 每轮 `dat → LCC → pch → pch_to_lib → lib` 重算几何，链路完整。

### 1.2 7.3 形态差异（`D:\ATP\110\ganzi\fanji\M123\work.atp`，418 卡）

```
$INSERT, D:\ATP\work\results\short1.pch
$INSERT, D:\ATP\work\results\dahao2.pch
$INSERT, D:\ATP\work\results\long3.pch
...
```
8 条 `$INSERT`，无参数位、无排序、无节点名。**节点名的唯一载体是 pch 脚卡**（前 24 列）。

`$PARAMETER` 段 84 行，分两类：

```
REIAMP_I =20000. $$        ← 55 条中间变量，带行尾 $$
REIAMP   =REIAMP_I         ← 29 条别名，不带 $$
```

### 1.3 三个语法根因（逐项做最小复现确认）

| 根因 | 现象 | 最小复现 |
|---|---|---|
| 行尾 `$$` | ATP 报 FMT 错误，不产出 pl4 | `AA=1` 通过 / `AA=1 $$` FMT |
| 整数值无小数点 | 按整数格式解析，报 `KONST = 120` | `AA=1000` 失败 / `AA=1000.` 通过 |
| 中间变量引用数超表 | 引用型变量 > `List31=10` → CIDEAL | 84 行 → 内联成 29 行后通过 |

三处全改后：`rc=0`、`pl4=369665`、`ATP Finished`、无 KILL，仅 3 条 TACS 源重名 Warning。
TACS / BRANCH / SWITCH / SOURCE 段**一行未动**。

参数敏感性验证（证明电气参数真的进了计算，不是被忽略）：

| 改动 | pl4 字节 | pl4 md5 |
|---|---|---|
| 基线 | 369665 | a39b2ed55145 |
| REIAMP 20000. | 369665 | ec08d22becaa |
| REIAMP 5000. | 369665 | 727a8bcede39 |
| PHAGA 30. | 369665 | c6fbd1a135ef |

字节数不变但 md5 全变 —— 波形结构相同、数值不同，符合"参数已生效"的预期。

### 1.4 批量 8 模型：4 通 4 不通

| 结果 | 模型 | 失败原因 |
|---|---|---|
| ✅ | 110/ganzi M123 | 参数段 84→29 后通过 |
| ✅ | 110/guxing | 同上 |
| ✅ | 220/jiubei | 同上 |
| ✅ | 220/maotou | 同上 |
| ❌ | 500/shangzi | 参数段只有 `NAME=NAME_I` 无中间变量定义 → TACS 报 `REHGI` 找不到 |
| ❌ | 110/sihuitano | 同上 |
| ❌ | 230/sihuita | KILL=12，`X0595A` 不在 branch/switch 里 |
| ❌ | 230/guxingd | KILL=17，稳态就崩 |

结论：这 4 个是**模型自身的结构缺陷**，规范化解决不了，需要逐模型诊断或拒收。

### 1.5 四个"看起来是原因但不是"的误判（避免再走一遍）

| 误判 | 真相 |
|---|---|
| TACS 段是报错源 | 删光 TACS 段仍报同样错误 |
| 10 字符符号名超限 | 老模型也有 `REIAMP____`，照样跑通 |
| 引擎容量不足需重编译 LISTSIZE | 400 条纯参数两引擎都通过；`LISTSIZE.DAT` 运行时无法改 `List31` |
| mytpbig 与 tpbig 不同代 | 引擎自打印均为 `Source code date is 19 September 2003`，mytpbig 只是 2022 年重新 VARDIM 编译 |

### 1.6 最危险的一条：pch 串味（静默错误）

`ATPDraw.ini` 只有一行 `[Directories] ATP=C:\ATP\work\results\` —— **全局唯一输出目录**，
ATPDraw 从不清理历史 pch。

实测证据：

| pch | 导体数 | 半径 | 坐标 X | 实际来源 |
|---|---|---|---|---|
| `C:\ATP\work\results\long3.pch` | 6 | .07389 | -4.8 / -6.1 / -5.2 / 4.8 | `230\guxingd\raoji2\M123` |
| `110\ganzi\fanji\M123\long3.pch` | 5 | .2744 | -6.8 / 0 / 6.8 | 本工程 |

204 个工程共用这 8 个文件名，**最后写入者赢**。此时仿真照样 `rc=0` 跑完，几何却是别人的线路。

### 1.7 判定判据：只看返回码必漏判

`$INSERT` 引用的 pch 缺失时：`rc=0`、`pl4=0 字节`，只有 `.lis` 里有
`Failure to connect disk file in CIMAGE. Halt.`

另外 mytpbig 解析失败返回 `RC=3`，tpbig 返回 `0` —— 可多一条判据。

**成功判据必须是三条合取**：`rc == 0 && pl4_size > 0 && lis 无 KILL/Failure`。

### 1.8 pch → 源 dat 映射（110/ganzi，逐字节验证）

| 编号 pch | 数值行数 | 源 dat |
|---|---|---|
| long3、long5 | 146 | long.dat |
| short1、short4、short6、short7 | 104 | short.dat |
| dahao2 | 104 | dahao.dat（与 short 同值） |
| xiaohao8 | 110 | xiaohao.dat |

节点名各不相同，且除被电源卡引用的 `XXSS2A` 外，在 work.atp 里**查不到**。

---

## 2. LP 现状缺口（逐文件）

| 位置 | 现状 | 7.3 下的后果 |
|---|---|---|
| `atp_asset_service.py:83` `_ALLOWED_ATP_MODEL_EXTENSIONS` | 只收 `.atp` / `.dat` | pch 传不进来 → `$INSERT` 必然打不开 |
| `atp_asset_service.py:486` `_validate_atp_entry_content` | 见 `$INSERT` 直接 400 | 7.3 模型 100% 被拒 |
| `atp_dat_writer.py:456` `_BRANCH_HEAD` | `^-?\d+(IN_+[A-Z0-9]+?)(OUT[A-Z0-9_]+)` | 不匹配 7.3 的 `-1X0133AXXSS2A` → `pch_to_lib` 抛「找不到数据起点」 |
| `atp_geometry_pipeline.py:278` | 固定遍历 `long/short/dahao/xiaohao` | 7.3 的 8 个序号 pch 不在这套命名里 |
| `atp_slot_scanner.py:51` `_PARAM_RE` | `^\s*([A-Z][A-Z0-9_]*)\s*=\s*(\S+)\s*$` | 对 `REIAMP_I =20000. $$` 会把 `$$` 当值；中间变量名被当槽位 |
| `fl_analysis_external.py:939` `_CSHARP_EQUALS_PARAM_RE` | 同上，右侧限 `[A-Za-z0-9_]+` | 7.3 模板判不成 C# 等号模板 → 参数根本不会写进去 |
| `fl_analysis_external.py:942` `_looks_like_csharp_equality_template` | 只看 `NAME=NAME_I` | 7.3 有 55 条带 `$$` 的行，采样判断可能失准 |
| `atp_asset_test_service.py:1037` `apply_runtime_slots` | 写 `11K0` / `14XXSS` 用固定列宽 | 7.3 的槽位行格式不同，按偏移写会错列 |
| `fl_analysis_external.py:1969` `_INCLUDE_PATH_RE` | 已支持 `.pch` | ✅ 无需改（2026-09-29 已修） |
| `fl_analysis_external.py:2091` `_materialize_asset_files` | 遍历整个 storage_root | ✅ 只要 pch 能上传就会物化 |

---

## 3. 支持方案

### 3.1 上传层：形态识别 + 完整性校验（P0）

**放开 pch 白名单**，但只在 7.3 形态下允许，且必须做闭合校验。

```python
# atp_asset_service.py
_ALLOWED_ATP_MODEL_EXTENSIONS = (".atp", ".dat", ".pch")
```

`_validate_atp_entry_content` 改为「分支判定 + 校验」而不是「见 INSERT 就拒」：

```python
_INSERT_CARD_RE = re.compile(r"(?mi)^[ \t]*\$INSERT[ \t]*,[^\n]*?([A-Za-z0-9_]+\.pch)")

def _validate_atp_entry_content(entry_path, content, member_names):
    text = content.decode("gbk", errors="replace")
    if _ATP_INSERT_CARD_RE.search(text):
        # ① pch 必须全部随包上传（同目录）
        refs = {m.group(1).lower() for m in _INSERT_CARD_RE.finditer(text)}
        missing = sorted(refs - {n.lower() for n in member_names})
        if missing:
            raise HTTPException(400, f"{entry_path} 引用的 pch 未随包上传：{', '.join(missing[:8])}")
        # ② 每个 pch 首行必须是分支头（脚卡），否则是半截文件
        # ③ 该工程不能同时存在 $INCLUDE .lib（混合形态）
        return  # 放行，标记为 insert 形态
```

**校验点（缺一不可）**：
1. `$INSERT` 引用的 pch 文件全部存在
2. 每个 pch 至少有一个分支头脚卡行（否则是残包）
3. 不得同时出现 `$INSERT` 与 `$INCLUDE .lib`（混合形态 LP 无法判定走哪条链路）

> 注意：第 1 条必须在**上传时**做，不能留到运行时 —— §1.7 已证明运行时缺文件是 `rc=0`。

### 3.2 参数层：三段规范化（P0，决定能不能跑）

7.3 模板进 LP 后，**必须在渲染后、写盘前**做一次规范化，输出给 mytpbig 吃的形态：

```
规范化三步（顺序不可换）：
① 解析：先解 55 条中间变量 NAME_I =值  → 得到 值表
② 内联：把 29 条别名 NAME =NAME_I 中的 NAME_I 替换成 ① 的值
③ 重写：$PARAMETER 段整体替换为「NAME=值」29 行，值必须带小数点，无 $$
```

顺序不可换的原因：别名引用中间变量，先解别名会被 `REIAMP_I` 这样的原名覆盖，
产生 `REAA1I.` 这类坏值（实测踩过）。

实现建议：新增 `atp_param_normalize.py`，纯函数、无 IO、可单测：

```python
def normalize_parameter_section(text: str) -> tuple[str, dict]:
    """7.3 $PARAMETER 段 → 引擎可解析形态。返回 (新文本, 诊断信息)。"""
    # 返回 diagnostics: {"intermediate": 55, "aliases": 29, "unresolved": [...]}
```

同时修两个正则：

```python
# atp_slot_scanner.py
_PARAM_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(\S+?)\s*(?:\$\$.*)?$")
# 但要显式跳过 *_I 结尾的中间变量，否则槽位列表里混进 55 个假槽位

# fl_analysis_external.py:939
_CSHARP_EQUALS_PARAM_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9_]*)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(?:\$\$.*)?$"
)
```

`apply_runtime_slots` 写 `11K0` / `14XXSS` 时**整数必须带小数点**（`%8.1f` 而不是 `%8d`），
否则触发 §1.3 的 KONST 错误。

### 3.3 几何层：三条路线（需决策）

这才是「全面支持」的真正分水岭。7.3 的 pch 由 ATPDraw 内部 LCC 生成，LP 无法命令行复现。

| 路线 | 做法 | 工作量 | 适用 | 风险 |
|---|---|---|---|---|
| **A. 模板固化** | 接受 pch 原样，几何不重算；一个资产 = 一座塔的固定几何 | 小（2~3 天） | ATP 测试页（同塔型同场景） | 换塔即错，但**不会静默错**——只要上传时锁定维度 |
| **B. 分组回填** | 解析 pch 分母结构 → LP LCC 生成新 pch → 按组替换数值区 | 大（1~2 周） | 生产计算（按杆塔重算） | 组内行数随 JMARTI 极点自适应，行数变化时整组替换会错位；需保留原始快照保证幂等 |
| **C. 降级为 lib** | 用 pch 脚卡的真实节点名 + LP LCC 数值，拼出 `$INCLUDE ... .lib` | 中（3~5 天） | 想复用现有 lib 链路 | 节点名映射（12 字符真实名 vs 6 字符占位名）+ 80 列卡宽限制 |

**推荐**：先落 A 打通全链路（上传→渲染→仿真→判定），再按需上 B。
C 的收益不如 A 直接，且 80 列限制会反复踩坑（私有目录路径已经为此做过短命名）。

B 的前置条件（必须先满足才能开工）：
1. `_BRANCH_HEAD` 支持 12 字符真实节点名，且能区分「导体组」与「极点行」
2. 建立 pch 分组 → dat 导体的顺序映射（7.3 的组顺序是否等于 dat 导体顺序 **未验证**）
3. 原始 pch 快照存档，保证重复执行幂等

### 3.4 执行层：判定与失败归因（P1）

```python
ok = (
    result.returncode == 0
    and pl4_path.exists() and pl4_path.stat().st_size > 0
    and not re.search(r"\bKILL\b|Failure to connect disk file", lis_text)
)
```

失败归因表（写入日志，前端可直接展示）：

| 现象 | 归因 | 提示 |
|---|---|---|
| rc=0 但 pl4=0 | pch 缺失 / 路径错 | 检查 `$INSERT` 目标是否物化到私有引擎目录 |
| `KILL=12` + 总线名 | 节点名不在 branch/switch | 模型结构缺陷，pch 节点名与 work.atp 引用不一致 |
| `KILL=17` | 稳态崩溃 | 参数值越界 |
| `KONST = N` | 整数格式 / 容量 | 检查小数点 |
| FMT 错误 | 行尾 `$$` 残留 | 规范化未生效 |
| CIDEAL + List31 | 中间变量未内联 | 规范化未生效 |

---

## 4. 落地顺序

**P0（不做就完全用不了）**
1. 放开 `.pch` 白名单 + `$INSERT` 三项闭合校验（§3.1）
2. `atp_param_normalize.py` + 接入 `stage_materialize`（§3.2）
3. 修 `_PARAM_RE` / `_CSHARP_EQUALS_PARAM_RE` / `apply_runtime_slots` 的格式
4. 成功判据改为三条合取（§3.4）

**P1（决定结果对不对）**
5. 几何路线 A：上传时锁定「资产 = 固定几何」，拒绝跨塔复用
6. 槽位扫描排除 `*_I` 中间变量，前端下拉不出现假槽位
7. 失败归因表接入测试报告

**P2（生产级）**
8. 几何路线 B：pch 分组回填（需先做可行性验证）
9. 引擎选型：验证 7.3 自带 tpbig 是否可直接吃 `$$`（若可以，P0-2 可整体删掉）

---

## 5. 验收矩阵

| 用例 | 期望 |
|---|---|
| 110/ganzi M123（7.3，84 行参数） | rc=0，pl4 > 0，参数敏感性 pl4 md5 变化 |
| 上传缺 1 个 pch | 上传即 400，不进运行队列 |
| 上传 pch 只有半截（无脚卡） | 上传即 400 |
| 230/sihuita | 失败但归因到 KILL=12 + 总线名，不是「未知错误」 |
| 老模型 4 样本 | pl4 字节数**逐字节不变**（回归） |
| 同一模型连跑两次 | 第二次结果幂等（md5 相同） |

---

## 6. 未验证项（不要当假设写进代码）

1. **7.3 自带引擎能否直接吃 `$$`** —— 若可以，整个 §3.2 可省。这是最高性价比的一次实验。
2. **7.3 pch 的分组顺序是否等于 dat 导体顺序** —— 决定路线 B 是否可行。
3. **7.3 的 dat 格式是否与 LP 现有 dat 同构** —— 影响路线 B/C 能否复用 `rewrite_dat_text`。
4. **`List31=10` 在其他 7.3 模型上的真实压力** —— 目前只验证了 ganzi 一个样本。

---

## 7. 实施记录（2026-11-02 已落地）

本轮实现的是 **识别 + 校验 + 分路 + 参数规范化**，几何路线取 A（模板固化，pch 随包不重算）。
路线 B（分组回填）未开工，前置条件见 §3.3。

### 7.1 新增文件

| 文件 | 作用 |
|---|---|
| `api/app/services/atp_model_format.py` | 形态识别 / 上传包预检 / `$PARAMETER` 规范化 / 运行期依赖检查。纯函数，不碰 DB 与存储，可单测 |
| `api/migrations/031_add_atp_asset_model_format.sql` | `atp_asset.model_format` + `format_check_json`（PG） |
| `api/migrations/mysql/032_add_atp_asset_model_format.sql` | 同上（MySQL） |
| `web/src/lib/atp-model-format.ts` | 前端形态标签 / 颜色 / Tooltip 说明 |

### 7.2 上传：从「见 `$INSERT` 就拒」改为「校验通过就收」

`atp_asset_service.py`：
- `_ALLOWED_ATP_MODEL_EXTENSIONS` 放开 `.pch`
- `_validate_atp_model_members` 只保留白名单 + 入口唯一性（`.dat` 齐不齐交给形态判定）
- 删除 `_validate_atp_entry_content`，新增 `_inspect_atp_package_or_400` / `_zip_members_for_check` / `_apply_format_report`
- 两个上传入口（zip 与散文件）都在**写盘前**预检，失败零写入
- 预检结果落到 `asset.model_format` + `asset.format_check_json`

**校验分级**（错误级 → 400 + 每条带修复动作；警告级 → 放行 + 前端展示）：

| 码 | 级 | 判据 |
|---|---|---|
| E001 | 错 | 没有 `work.atp` 且 `.atp` 不是恰好一个 |
| E010 | 错 | `$INSERT` 引用的 pch 未随包上传 |
| E011 | 错 | pch 无分支头脚卡（半截文件） |
| E012 | 错 | `$INSERT` 与 `$INCLUDE .lib` 混存 |
| E013 | 错 | `$PARAMETER` 段别名引用不到中间变量（TACS 必报「找不到」） |
| E014 | 错 | Enbed 形态（几何烧死） |
| E002 | 错 | 老版形态缺标准 `.dat` |
| W001 | 警 | 行尾 `$$`（LP 会自动去掉） |
| W002 | 警 | 整数值无小数点（LP 会自动补点） |
| W003 | 警 | 中间变量 > List31=10（LP 会内联） |
| W010 | 警 | 老版包内带 `.pch`（用不上，可删） |
| W011 | 警 | `$INSERT` 的 pch 来自多个目录（可能混入别的工程） |

### 7.3 仿真：按形态分路

`atp_asset_test_service.py`：

| 环节 | legacy | insert |
|---|---|---|
| `stage_materialize` | 原样 | 追加 `normalize_parameter_section`（去 `$$` / 整数补点 / 内联中间变量），解析不完整则中止 |
| `stage_geometry` | `dat → LCC → pch → lib` | **跳过 LCC**，改为校验 `$INSERT` 的 pch 是否都已物化，缺一个直接中止 |
| `apply_runtime_slots` | 写 `14XXSS` 固定列 | **跳过**（7.2+ 的 SOURCE 相角是 TACS 变量 `PHAGA_____`，按固定列写会错列） |
| 几何对拍 | 比 4 个 `.lib` 的 sha256 | 比 `$INSERT` 引用 pch 的 sha256 |
| 成功判据 | `rc==0 && pl4>0 && lis 无致命行` | 同左 |

`fl_analysis_external.py`：
- `_rewrite_includes` 的 `$INSERT` 分支改为「按文件名重构路径」，不再依赖 `D:\ATP\` 前缀
  （`ATPDraw.ini` 的 `[Directories] ATP=` 有 `C:\` / `D:\` 两种写法；原正则对 C 盘不匹配
  → 不重写 → 去读全局共享目录里别的工程的 pch，仿真照跑但几何错）

### 7.4 判定修正：`KILL = N` 此前是漏判的

`_lis_has_halt` 旧实现只认 `KILL-CODE`，而 ATPMingw 实际输出是 `KILL = 1.` / `KILL = 12`。
实测 `D:\ATP\110\sihuita\fanji\noM\work.lis` 命中 `KILL = 1.  Storage exceeded for EMTP List Number 8.`
—— 旧逻辑会把它判成通过。现已补 `\bKILL\s*=` 与 `Failure to connect disk file` 两个模式。

### 7.5 槽位扫描修正

`atp_slot_scanner._PARAM_RE` 改后能吃掉行尾 `$$`，并新增 `is_intermediate_slot()` 排除
`*I` 中间变量。实测：

| 模型 | 修正前 | 修正后 |
|---|---|---|
| 110/ganzi M123（7.3） | 84 槽位（含 55 个假槽位） | **29 槽位**（= 别名数） |
| 110/guxing M123（老版） | 28 | 28（无变化） |

### 7.6 验证证据

| 项 | 结果 |
|---|---|
| 7.3 规范化产物直接跑 mytpbig | `rc=0`、`pl4=369665` 字节、`ATP Finished`、无 KILL |
| 渲染 → 规范化链路（基线与两处改参） | REIAMP 20000→5000 波形指纹变；PHAGA→30 波形指纹变（均 `rc=0`、369665 字节） |
| 老版样本直通 | 参数段 `rewritten=False`（有中间变量才重写，老式单层不触发） |
| 预检：7.3 完整包 | 0 error / 3 warning |
| 预检：7.3 去掉全部 pch | E010 |
| 预检：老版包 | 0 error / 1 warning（W010） |
| 前端类型检查 | 改动文件 0 错误（`npx tsc --noEmit` 仅存留 2 处与本次无关的既有错误） |

> 注：`work.pl4` 头部含运行时刻（`02-Nov-26 22:00:07`），同一输入两次运行的 md5 必然不同，
> 判等必须用「字节数 + 跳过头部后的波形区指纹」，不能用整文件 md5。

### 7.7 仍需人工介入的场景

程序保证「拿到的模型是完整的」，但不保证「模型本身算得对」。以下情况会在测试报告的
verdict 里显式失败，需要人工改模型：

- `230/sihuita`：`X0595A` 不在 branch/switch → `KILL = 12`
- `230/guxingd`：稳态崩溃 → `KILL = 17`
- 参数段只有别名没有定义的残缺模板 → 上传阶段 E013 就拦掉

