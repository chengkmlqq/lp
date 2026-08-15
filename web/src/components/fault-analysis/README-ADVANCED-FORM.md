# 故障分析表单 - 高级版本

## 更新内容

基于 Pencil 设计稿 "Form Demo (Empty)"，实现了完整的三步骤故障分析创建表单。

## 表单结构

### 第一步：故障线路 ①

**必填字段：**
- **故障线路选择** - 从线路列表中选择

### 第二步：故障信息 ②

包含 Excel 导入功能按钮和以下字段：

**基础信息：**
- 录波记录厂站 （必填）
- 故障时刻 （必填）
- 故障线路名称 （必填）
- 故障相 （必填，下拉选择：A/B/C/AN/BN/CN/AB/BC/AC/ABC/ABN/BCN/ACN）
- 故障持续时间(ms) （必填）

**电气参数：**
- 重合闸情况 （必填，下拉选择：成功/失败/不适用）
- 故障相电压(V)
- 故障相电流(A)
- 最大零序电流(A)
- 零序补偿系数K
- 故障电阻Rm(Ω)

**线路参数：**
- 线路总长度L(km)
- 线路正序灵敏角(°)
- 线路正序阻抗定值(Ω)

**雷电定位：**
- 雷电流幅值I(kA)
- 雷电定位经度(°)
- 雷电定位纬度(°)

**测距数据：**
- 录波测距(km)
- 行波测距(km)

**光学监控：**
- 光学接闪位置(绕击/反击/分叉)
- 光学设备安装位置

### 第三步：分析数据 ③

**文件上传卡片（2x2 网格布局）：**

1. **录波数据**
   - 图标：FileTextOutlined
   - 支持格式：.txt
   - 文件限制：单文件

2. **雷电定位数据**
   - 图标：TableOutlined
   - 支持格式：.xls/.xlsx
   - 文件限制：单文件

3. **分布式行波数据**
   - 图标：LineChartOutlined
   - 支持格式：.csv/.dat
   - 文件限制：单文件

4. **光学监控数据**
   - 图标：CameraOutlined
   - 支持格式：图片或视频
   - 文件限制：单文件

## 设计特点

### 视觉层次

1. **步骤标题栏**
   - 深色背景（bg-slate-900）
   - 白色文字
   - 步骤序号 + 标题
   - 第二步包含右侧操作按钮

2. **表单字段布局**
   - 响应式网格布局
   - 单字段：全宽
   - 双字段：2列等宽
   - 三字段：3列等宽
   - 字段间距一致

3. **文件上传卡片**
   - 浅灰背景（bg-gray-50）
   - 边框圆角
   - 垂直居中布局
   - 图标 + 标题 + 格式说明 + 上传按钮

### 用户体验

- **滚动区域**：表单内容支持滚动（max-h-[70vh]）
- **必填提示**：关键字段标记为必填
- **下拉选项**：预设选项（故障相、重合闸情况）
- **输入类型**：数字字段使用 type="number"
- **占位符**：所有字段提供示例数据

## 文件清单

```
src/components/fault-analysis/
├── create-analysis-form.tsx              # 原简化版表单（保留）
├── create-analysis-form-advanced.tsx     # 新增详细表单 ✨
└── types.ts                              # 更新类型定义 ✨
```

## 组件 Props

```typescript
interface CreateAnalysisFormAdvancedProps {
  form: FormInstance<CreateFaultAnalysisFormValues>;
  lines: Array<{ id: string; name: string; code: string }>;
  linesLoading?: boolean;
  onSubmit: (values: CreateFaultAnalysisFormValues) => void;
  submitText?: string;   // 提交按钮文案（新建「提交分析」/ 编辑「保存修改」）
  submitting?: boolean;  // 提交中加载态
}
```

## 使用方法

在动态选项卡（`create-analysis-form-tab.tsx`，LP-348）中已更新为使用新表单：

```typescript
<CreateAnalysisFormAdvanced
  form={form}
  lines={lines}
  linesLoading={linesLoading}
  submitText="提交分析"
  submitting={submitting}
  onSubmit={onSubmit}
/>
```

## 数据结构

表单提交的数据包含：

- 线路 ID
- 18+ 个故障信息字段
- 4 个文件上传字段

完整类型定义见 `types.ts` 文件。

## 后续改进

- [ ] 实现 Excel 导入功能
- [ ] 添加字段间的联动验证
- [ ] 实现文件预览功能
- [ ] 添加表单数据保存草稿
- [ ] 优化移动端表单布局
- [ ] 添加字段提示和帮助文档

## 技术栈

- Ant Design Form
- Ant Design Upload
- Ant Design Icons
- Tailwind CSS
- TypeScript
