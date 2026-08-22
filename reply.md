### 开发结果

**改动摘要：**
- 新增 `execute_binary_search_external()`（`api/app/services/fl_analysis_external.py`），以 ATP 单次波形执行为基础，对雷电流做折半逼近：上限值取为临界耐雷水平，并结合 `stroke_mode` 输出 `counterstrike_withstand_ka` / `shielding_withstand_ka`；每个迭代记录写入 `result_json["binary_search"]`。
- 在 `fl_analysis_service.py` 的 `normal` / `tongtiao` 外部 ATP 执行分支中，当 `execution_options.binary_search=true` 时走二分迭代，否则保持原有单次 ATP 执行。
- `api/app/schemas/fl_analysis.py` 的 `FlAnalysisWaveformExecutionOptions` 增加 `binary_search` 及上下限/精度字段。
- Web 端：`types.ts` 的 `CreateJobFormValues` / `CREATE_JOB_DEFAULTS` 增加对应字段；`create-job-form.tsx` 在 ATP 模型选择后新增“二分迭代”开关与参数表单；`page.tsx` 的 `buildCreateJobPayload` 在开启时向 `execution_options_json` 下发该配置。

>> **语法/静态检查结果：**
>> - Python：`py_compile` 通过（`fl_analysis_external.py`、`fl_analysis_service.py`、`fl_analysis.py` 均无语法错误）。
>> - Web：仅静态审查，未安装依赖的情况下不执行 `eslint`；`create-job-form.tsx`、`page.tsx`、`types.ts` 为常规表单逻辑，未引入新的编译风险。
>> - 未运行后端/前端编译与单元测试。

**提交信息：**
- 提交哈希：待提交
- 推送分支：待推送

**注意事项：**
- 二分迭代仅在 `normal`/`tongtiao` 外部 ATP 任务且选择了 ATP 模型时生效。
- ATP 模板中会注入 `binary_search_current_ka` 字段，模板侧需据此替换电流变量。
- 若 ATP 输出里 `flashover_phase` 为非空字符串，Python 侧会自动统计逗号分隔相数作为 `flashover_count`。
