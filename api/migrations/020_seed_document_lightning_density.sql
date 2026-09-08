-- 020: 种子数据 - 文档管理：地闪密度计算与使用说明（LP knowledge 老工程知识）
-- 幂等：章节按 name 防重、文档按 title 防重；已存在时跳过（不覆盖人工修改）。
-- 发布/重置部署库时执行本文件即可自动加载该知识条目。

-- 1) 章节：防雷计算知识（固定 id=1001，避免与自增冲突；已存在同名校则不重复插入）
INSERT INTO document_chapters (id, name, description, parent_id, sort_order)
SELECT 1001, '防雷计算知识', 'LP 防雷计算相关的原理、公式与数据流转说明', NULL, 10
WHERE NOT EXISTS (SELECT 1 FROM document_chapters WHERE name = '防雷计算知识');

-- 2) 文档：地闪密度计算与使用说明（固定 id=1001；已存在同名标题则不重复插入）
INSERT INTO documents (id, title, content, chapter_id, sort_order, status)
SELECT 1001,
       '地闪密度计算与使用说明（LP knowledge 老工程）',
       E'# 地闪密度计算与使用说明

## 一句话说明

地闪密度计算做的是：算出线路每座塔头顶上一年每平方公里会挨多少次雷（Ng），并给每座塔贴一个数字，同时画一张「沿线一串圆」的地图。

## 老工程（LP knowledge C# 桌面版）计算流程

入口：FormDiShanMiDu.cs（地闪密度计算绘制），共 6 步：

1. **电压分级**：35/66/110kV → banjin1.exe；220/330kV → banjin2.exe；500/750/800/1000kV → banjin3.exe（分组塔数与圆半径不同）。
2. **写杆塔坐标 CSV**：`地闪密度文件夹/杆塔坐标.csv`，表头 `电压等级,杆塔经度,杆塔纬度`，每塔一行。
3. **调用 banjinN.exe**（Python 打包，pandas+matplotlib+shapely）→ 生成 `区域雷击统计_简版.csv` 与沿线圆地图 PNG。
4. **回写每塔 mDSMD_GanTa**：读 CSV 第 7 列（地闪密度），按组索引 j/num4 映射到塔（越界取最后一个）。

核心机制：
- 杆塔按电压等级分组：35/66/110kV 每 2 塔一组、220/330kV 每 3 塔一组、500kV 以上每 5 塔一组。
- 每组取组内塔经纬度均值作圆心，画半径 1~3km 的圆（km_to_deg：1 度≈111km），unary_union 合并缓冲区，再做 Voronoi 式中垂线分割。
- 统计每组圆/多边形内落雷数 → 落雷数 ÷ 面积 ÷ 年数 = 地闪密度 Ng（次/km²·年），同组塔共用该值。

字段存储：`GanTaData.mDSMD_GanTa`（默认值 2.8 次/km²·年），随塔保存、随 CSV 导入导出、随参数串传给 DLL。

## 计算消费（DLL 内 mParamSet.m地闪密度）

地闪密度（Ng）是跳闸率计算的直接乘数，出现在三条链路：

### ① 反击跳闸率（ComputeLightningProtection.cs fjtzl500800DC）

    fjTZL = 0.1 × Ng × (2×右避雷线中距 + 4×避雷线高度) × 建弧率 / (6 或 4) / (1 + (耐雷水平/雷电流幅值a)^b)

- 平地（|倾角1|<10° 且 |倾角2|<10°）→ 除以 6；山地（任一 ≥10°）→ 除以 4
- 建弧率：110kV=0.85、220kV=0.918、其余=1

### ② 绕击跳闸率（rjtzl_GCF）

    rjTZL = 0.1 × Ng × (2×右避雷线中距 + 4×避雷线高度) × 建弧率 × 10^(α×√避雷线高度/86 - 3.9) / (1 + (绕击耐雷水平/a)^b)

- 平地指数 -3.9，山地 -3.35
- 建弧率分级：35/66=0.8、110=0.85、220=0.918、330=0.95、≥500=1.0

### ③ 风险等级划分（MyRiskRating）

    折算值 S = (反击跳闸率 + 绕击跳闸率) × 2.78 / 地闪密度

- S ≤ ck → 1级；≤1.5ck → 2级；≤3ck → 3级；>3ck → 4级
- ck 参考值（交流）：35kV=0.8、66=0.65、110=0.525、220=0.315、330=0.2、500=0.14、750/1000=0.1
- 直流：400/500=0.15、660/800=0.1

注意反直觉特性：S = 跳闸率×2.78/Ng，Ng 越大折算值 S 越小、风险等级越低。

## Web 端对应实现

Web 端 fl_analysis_rules.py 已复刻同款公式：
- _calculate_counterstrike_trip_rate / _calculate_shielding_trip_rate：同款 0.1×Ng×(...)×建弧率/(6 或 4)/(1+(I/a)^b) 结构
- _calculate_risk_grade：risk_index = 总跳闸率×2.78/density，阈值按电压分级，等级划分与 C# 一致
- 数据来源：落雷数据回填 prepare-line-density，存储于 line_tower.lightning_density

## 要点总结

| 环节 | C# 桌面版 | Web 端 |
|------|----------|--------|
| 数据来源 | banjinN.exe 分组统计 + 杆塔坐标 CSV | 落雷数据回填 |
| 存储 | mDSMD_GanTa（默认 2.8） | line_tower.lightning_density |
| 消费 | 跳闸率×Ng、风险等级 S=跳闸率×2.78/Ng | 同款公式（已复刻） |
| 附加 | 沿线圆密度图（banjin 出 PNG） | 「沿线圆」图复刻（commit 2c08f67） |

地闪密度在 C# 里不是计算目标，而是跳闸率/风险等级计算的输入乘数。',
       1001, 10, 'published'
WHERE NOT EXISTS (SELECT 1 FROM documents WHERE title = '地闪密度计算与使用说明（LP knowledge 老工程）');
