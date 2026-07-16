# Excel导入功能使用示例

## 功能概述

故障分析表单新增了Excel导入功能，支持批量导入故障信息数据，提高数据录入效率。

## 功能特性

### 1. 模板下载
- 点击"下载模板"按钮，自动下载标准的Excel模板
- 模板包含所有必填和可选字段的表头
- 提供示例数据供参考

### 2. 数据导入
- 支持 `.xlsx` 和 `.xls` 格式
- 自动解析Excel数据并填充到表单
- 支持数据类型自动转换
- 提供友好的错误提示

### 3. 数据验证
- 自动验证必填字段
- 数值字段自动转换类型
- 重合闸情况自动映射（成功→success）

## 使用流程

```
1. 点击"下载模板" → 2. 填写Excel数据 → 3. 点击"Excel导入" → 4. 选择文件 → 5. 数据自动填充
```

## 代码实现

### 核心文件

1. **excel-import-utils.ts** - Excel导入工具函数
   - `parseExcelFile()` - 解析Excel文件
   - `generateImportTemplate()` - 生成导入模板

2. **create-analysis-form-advanced.tsx** - 表单组件
   - 集成Excel导入按钮
   - 处理文件上传和数据填充

### 字段映射

```typescript
const FIELD_MAPPING = {
  '录波记录厂站': 'station_name',
  '故障时刻': 'fault_time',
  '故障线路名称': 'fault_line_name',
  '故障相': 'fault_phase',
  // ... 更多字段
}
```

### 使用示例

```tsx
import { parseExcelFile, generateImportTemplate } from '@/lib/excel-import-utils';

// 下载模板
const handleDownloadTemplate = () => {
  generateImportTemplate();
};

// 导入Excel
const handleExcelImport = async (file: File) => {
  const data = await parseExcelFile(file);
  form.setFieldsValue(data);
};
```

## Excel模板格式

### 表头（第一行）

| 录波记录厂站 | 故障时刻 | 故障线路名称 | 故障相 | 故障持续时间(ms) | ... |
|------------|---------|------------|-------|----------------|-----|

### 数据行（第二行开始）

| 广东河源500kV上寨变 | 2023-03-27 20:20:31.939 | 220kV 龙和线 | AN | 64 | ... |
|------------------|----------------------|------------|----|----|-----|

## 技术实现

### 依赖库

```json
{
  "xlsx": "^0.18.5"  // Excel文件处理
}
```

### 核心逻辑

1. **文件读取**
```typescript
const reader = new FileReader();
reader.readAsBinaryString(file);
```

2. **Excel解析**
```typescript
const workbook = XLSX.read(data, { type: 'binary' });
const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 });
```

3. **数据转换**
```typescript
// 数值类型转换
value = typeof value === 'number' ? value : parseFloat(value);

// 重合闸情况映射
const mappedValue = RECLOSURE_MAPPING[value] || value;
```

4. **模板生成**
```typescript
const ws = XLSX.utils.aoa_to_sheet([headers, exampleData]);
const wb = XLSX.utils.book_new();
XLSX.utils.book_append_sheet(wb, ws, '故障信息模板');
XLSX.writeFile(wb, '故障信息导入模板.xlsx');
```

## 错误处理

### 常见错误

1. **文件格式错误**
   - 错误信息：`读取文件失败`
   - 解决方法：确保文件格式为 `.xlsx` 或 `.xls`

2. **数据格式错误**
   - 错误信息：`Excel文件格式不正确，至少需要包含表头和一行数据`
   - 解决方法：确保Excel包含表头和数据行

3. **字段映射失败**
   - 现象：部分数据未填充
   - 解决方法：检查表头名称是否与模板一致

### 错误处理代码

```typescript
try {
  const data = await parseExcelFile(file);
  form.setFieldsValue(data);
  message.success('Excel数据导入成功');
} catch (error) {
  message.error(`导入失败: ${error.message}`);
}
```

## 扩展功能

### 未来可扩展的功能

1. **批量导入**
   - 支持一次导入多行数据
   - 生成多个故障分析记录

2. **数据验证增强**
   - 导入前验证数据格式
   - 显示详细的验证错误信息

3. **字段映射配置**
   - 支持自定义字段映射
   - 适配不同的Excel模板格式

4. **导入历史记录**
   - 记录导入历史
   - 支持重新导入之前的文件

## 相关文件

- `/web/src/lib/excel-import-utils.ts` - 核心工具函数
- `/web/src/components/fault-analysis/create-analysis-form-advanced.tsx` - 表单组件
- `/web/public/故障信息导入说明.md` - 用户使用说明

## 测试

运行测试：
```bash
npm test excel-import-utils
```

手动测试：
1. 启动开发服务器
2. 打开故障分析页面
3. 点击"新建分析"
4. 测试"下载模板"和"Excel导入"功能
