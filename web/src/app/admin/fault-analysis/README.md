# 故障分析页面

## 概述

故障分析页面用于对电力线路进行故障分析，识别风险点并提供改造建议。

## 功能特性

### 主要功能
- **故障分析列表**：以卡片网格形式展示所有故障分析记录
- **搜索功能**：支持按名称、线路名称或描述进行搜索
- **详情查看**：查看故障分析的详细信息、参数和结果
- **新建分析**：创建新的故障分析任务

### 分析类型
- 雷击故障分析
- 绝缘故障分析
- 导线故障分析
- 杆塔故障分析
- 综合故障分析

### 风险等级
- **低风险** (low)：绿色标识
- **中风险** (medium)：黄色标识
- **高风险** (high)：红色标识
- **严重** (critical)：深红色标识

### 状态管理
- **待处理** (pending)：分析任务已创建，等待执行
- **处理中** (processing)：分析任务正在执行
- **已完成** (completed)：分析任务执行成功
- **失败** (failed)：分析任务执行失败

## 文件结构

```
src/
├── app/admin/fault-analysis/
│   └── page.tsx                          # 主页面组件
└── components/fault-analysis/
    ├── types.ts                          # TypeScript 类型定义
    ├── analysis-card.tsx                 # 分析卡片组件
    ├── analysis-card-list.tsx            # 卡片列表组件
    ├── create-analysis-form.tsx          # 创建分析表单
    └── analysis-detail-panel.tsx         # 详情面板组件
```

## 组件说明

### AnalysisCard
单个故障分析卡片，显示：
- 标题
- 状态徽章
- 风险等级
- 描述
- 线路名称
- 杆塔数量

### AnalysisCardList
故障分析卡片网格列表，支持：
- 响应式布局（1-3列）
- 选中状态
- 加载状态
- 空状态

### CreateAnalysisForm
创建新分析的表单，包含：
- 分析名称（必填）
- 线路选择（必填）
- 分析类型（必填）
- 描述（可选）

### AnalysisDetailPanel
显示故障分析详情：
- 基本信息
- 状态和风险标签
- 创建/更新时间
- 分析参数（JSON 格式）
- 分析结果（JSON 格式）

## 权限要求

- **查看权限**：需要 `line.read` 或 `line.manage` 权限
- **创建/管理权限**：需要 `line.manage` 权限

## API 集成

当前使用模拟数据，实际使用时需要实现以下 API：

### 获取分析列表
```
GET /api/v1/fault-analysis
Response: { items: FaultAnalysis[] }
```

### 获取分析详情
```
GET /api/v1/fault-analysis/{id}
Response: FaultAnalysisDetail
```

### 创建分析
```
POST /api/v1/fault-analysis
Body: CreateFaultAnalysisFormValues
Response: { analysis: FaultAnalysisDetail }
```

## 使用方法

1. 访问 `/admin/fault-analysis` 路径
2. 查看现有的故障分析记录
3. 使用搜索框过滤分析记录
4. 点击卡片查看详细信息
5. 点击"新建分析"按钮创建新的故障分析任务

## 设计参考

该页面基于 Pencil 设计稿中的 "Fault Analysis List" 实现，采用：
- 卡片网格布局
- 现代化的 UI 设计
- 清晰的信息层级
- 响应式设计

## 技术栈

- **React 19**：UI 框架
- **Next.js 16**：应用框架
- **Ant Design 5**：UI 组件库
- **TanStack Query**：数据获取和状态管理
- **TypeScript**：类型安全
- **Tailwind CSS**：样式

## 后续改进

- [ ] 实现真实的 API 集成
- [ ] 添加分析结果的可视化图表
- [ ] 支持导出分析报告
- [ ] 添加分析历史记录
- [ ] 实现批量操作功能
- [ ] 添加更详细的分析参数配置
