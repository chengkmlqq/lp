import { App, Form, Input, Select, Button, FormInstance, Space, Steps, Alert, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { FileTextOutlined, TableOutlined, LineChartOutlined, CameraOutlined, DownloadOutlined } from "@ant-design/icons";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { CreateFaultAnalysisFormValues } from "./types";
import { TempFileUpload } from "./temp-file-upload";
import type { FaultAnalysisTempFile } from "./types";
import { useI18n } from "@/lib/i18n";
import { generateWaveDataTemplate, generateLightningTemplate, generateWaveTemplate, generateOpticalTemplate } from "@/lib/excel-import-utils";
import * as XLSX from "xlsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { LineTowerListResponse, LineTowerSummary } from "@/types/auth";

interface CreateAnalysisFormAdvancedProps {
  form: FormInstance<CreateFaultAnalysisFormValues>;
  lines: Array<{ id: string; name: string; code: string }>;
  linesLoading?: boolean;
  onSubmit: (values: CreateFaultAnalysisFormValues) => void;
  submitText?: string;
  submitting?: boolean;
  /** 弹窗是否处于打开状态（用于弹窗重开时复位到第一步，参照防雷任务分步表单） */
  open?: boolean;
}

/** 分步配置（LP-546）：故障线路 → 故障信息 → 分析数据，与防雷计算任务新建表单一致。 */
const STEP_TITLES = ["故障线路", "故障信息", "分析数据"];

/** 线路杆塔列表服务端分页大小（一次查 15 条，翻页再按 15 条递增拉取） */
const TOWER_PAGE_SIZE = 15;

// 各步骤进入下一步时需要校验的字段（参照防雷 goNext 的按步校验策略）
const STEP_REQUIRED_FIELDS: Array<Array<keyof CreateFaultAnalysisFormValues>> = [
  ["title", "line_id"],
  ["station_name", "fault_time", "fault_line_name", "fault_phase", "reclosure_status"],
  [],
];

/** 数值字段提取值清洗：去掉单位/千分位等杂字符，解析失败返回 undefined（保证回填进 type="number" 输入框） */
function toNumber(value: unknown): number | undefined {
  if (typeof value === "number") {
    return Number.isNaN(value) ? undefined : value;
  }
  if (typeof value !== "string") {
    return undefined;
  }
  const cleaned = value.replace(/[，,]/g, "").replace(/[^\d.\-]/g, "");
  if (!cleaned) {
    return undefined;
  }
  const parsed = Number(cleaned);
  return Number.isNaN(parsed) ? undefined : parsed;
}

/** 重合闸文本 → 枚举码（第二步 Select 选项为 success/failed/not_applicable，提取结果常为中文文本） */
function toReclosureCode(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return value as string | undefined;
  }
  if (/成功|success/i.test(value)) {
    return "success";
  }
  if (/失败|fail/i.test(value)) {
    return "failed";
  }
  return "not_applicable";
}

export function CreateAnalysisFormAdvanced({ form, lines, linesLoading, onSubmit, submitText, submitting, open = false }: CreateAnalysisFormAdvancedProps) {
  const { t } = useI18n();
  const submitLabel = submitText ?? t("提交分析");
  const { message: messageApi, modal: modalApi } = App.useApp();
  const { user, fetchWithAuth } = useAuth();
  const [currentStep, setCurrentStep] = useState(0);
  const [prevOpen, setPrevOpen] = useState(open);
  // 最近一次步骤切换的时间戳（防连点：同位置按钮替换导致的误点击）
  const lastStepChangeAtRef = useRef(0);
  const [extractState, setExtractState] = useState<{
    response: { ok: boolean; extracted: Record<string, unknown>; missing: string[]; ocr_used: boolean; raw_text_preview?: string };
    item: FaultAnalysisTempFile;
  } | null>(null);

  // 选中线路 → 拉取该线路杆塔列表（参照防雷计算任务新建表单的「线路杆塔」区块）；
  // 服务端分页，一次查 TOWER_PAGE_SIZE 条（15），翻页时按 offset 递增拉取。
  const selectedLineId = Form.useWatch("line_id", form) ?? "";
  const [towerPage, setTowerPage] = useState(1);
  const [prevLineId, setPrevLineId] = useState(selectedLineId);
  // 切换线路时回到第一页（渲染期调整，避免 effect 内 setState）
  if (selectedLineId !== prevLineId) {
    setPrevLineId(selectedLineId);
    setTowerPage(1);
  }
  const towersQuery = useQuery({
    queryKey: ["/api/v1/lines", selectedLineId, "towers", towerPage],
    enabled: !!user && !!selectedLineId,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const params = new URLSearchParams({
        limit: String(TOWER_PAGE_SIZE),
        offset: String((towerPage - 1) * TOWER_PAGE_SIZE),
      });
      const response = await fetchWithAuth(`/api/v1/lines/${selectedLineId}/towers?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
  });

  // 弹窗重新打开时回到第一步（渲染期调整，避免 effect 内 setState，参照防雷实现）
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setCurrentStep(0);
    }
  }

  const lastStepIndex = STEP_TITLES.length - 1;

  // 线路杆塔列表列（参照防雷计算任务新建表单）
  const towerColumns: ColumnsType<LineTowerSummary> = [
    { title: t("序号"), dataIndex: "seq_no", width: 70 },
    {
      title: t("塔号"),
      dataIndex: "tower_no",
      width: 130,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    { title: t("塔型"), dataIndex: "tower_type", width: 100, render: (value: string | null) => value || "-" },
    { title: t("模型"), dataIndex: "tower_model", width: 160, render: (value: string | null) => value || "-" },
    {
      title: t("接地电阻(Ω)"),
      dataIndex: "ground_resistance_ohm",
      width: 110,
      render: (value: number | null) => value ?? "-",
    },
    {
      title: t("地闪密度"),
      dataIndex: "lightning_density",
      width: 100,
      render: (value: number | null) => value ?? "-",
    },
  ];

  const goNext = async () => {
    // 防连点：步骤切换后极短时间内（同位置「下一步」→「提交」按钮替换）的重复点击
    // 可能误触发下一步跳级或直接提交（导致弹窗被关闭），统一忽略。
    const now = Date.now();
    if (now - lastStepChangeAtRef.current < 350) {
      return;
    }
    const fields = STEP_REQUIRED_FIELDS[currentStep];
    try {
      await form.validateFields(fields.map((field) => String(field)));
      setCurrentStep((step) => step + 1);
      lastStepChangeAtRef.current = Date.now();
    } catch {
      // 校验失败信息由 Form.Item 展示，停留在当前步骤
    }
  };

  const goPrev = () => {
    const now = Date.now();
    if (now - lastStepChangeAtRef.current < 350) {
      return;
    }
    setCurrentStep((step) => Math.max(0, step - 1));
    lastStepChangeAtRef.current = Date.now();
  };

  const waveFiles = Form.useWatch("wave_data_file", form) ?? [];
  useEffect(() => {
    if (!extractState) {
      return;
    }
    const stillExists = waveFiles.some((f) => f.uid === extractState.item.uid);
    if (!stillExists) {
      setExtractState(null);
    }
  }, [waveFiles, extractState]);

  const WAVE_FIELD_LABELS: Record<string, string> = {
    station: "录波记录厂站",
    fault_time: "故障时刻",
    line_name: "故障线路名称",
    fault_phase: "故障相",
    duration_ms: "故障持续时间",
    reclosing: "重合闸情况",
    phase_voltage: "故障相电压",
    phase_current: "故障相电流",
    zero_sequence_current: "最大零序电流",
    zero_sequence_compensation_k: "零序补偿系数K",
    line_length_km: "线路总长度L",
    sensitive_angle_deg: "线路正序灵敏角",
    positive_sequence_impedance_ohm: "线路正序阻抗定值",
  };

  const handlePdfExtracted = useCallback((item: FaultAnalysisTempFile, response: { ok: boolean; extracted: Record<string, unknown>; missing: string[]; ocr_used: boolean; raw_text_preview?: string }) => {
    setExtractState({ response, item });
    const extracted = response.extracted || {};
    const patch = {
      station_name: extracted.station ?? undefined,
      fault_time: extracted.fault_time ?? undefined,
      fault_line_name: extracted.line_name ?? undefined,
      fault_phase: extracted.fault_phase ?? undefined,
      fault_duration: toNumber(extracted.duration_ms),
      reclosure_status: toReclosureCode(extracted.reclosing),
      fault_voltage: toNumber(extracted.phase_voltage),
      fault_current: toNumber(extracted.phase_current),
      max_zero_current: toNumber(extracted.zero_sequence_current),
      zero_compensation: toNumber(extracted.zero_sequence_compensation_k),
      line_length: toNumber(extracted.line_length_km),
      line_angle: toNumber(extracted.sensitive_angle_deg),
      line_impedance: toNumber(extracted.positive_sequence_impedance_ohm),
    } as Parameters<typeof form.setFieldsValue>[0];
    // 线路联动：识别出的线路与第一步所选线路不一致时，能匹配到系统线路则自动切换 line_id，
    // 匹配不到则提示用户（避免台账按默认线路组装导致判别时线路查不到）。
    const extractedLineName = String(extracted.line_name ?? "").trim();
    if (extractedLineName) {
      const matchedLine = lines.find(
        (line) => line.name === extractedLineName || line.code === extractedLineName,
      );
      const currentLineId = form.getFieldValue("line_id");
      if (matchedLine) {
        if (currentLineId && currentLineId !== matchedLine.id) {
          patch.line_id = matchedLine.id;
          messageApi.info(`已按录波识别结果自动选择线路「${matchedLine.name}」`);
        } else if (!currentLineId) {
          patch.line_id = matchedLine.id;
        }
      } else if (currentLineId) {
        const currentLine = lines.find((line) => line.id === currentLineId);
        messageApi.warning(
          `录波识别的线路「${extractedLineName}」不在系统线路列表中，` +
            `${t("当前第一步选择的是")}「${currentLine ? `${currentLine.name} (${currentLine.code})` : t("未选择")}」，${t("请确认是否需要更换线路")}；` +
            t("否则判别时台账将按所选线路组装，无法匹配录波线路。"),
        );
      }
    }
    // 识别结果回填第二步故障信息表单（数值字段清洗单位、重合闸转枚举码，保证输入框/下拉可显示）
    form.setFieldsValue(patch);
  }, [form, lines, messageApi]);

  const handleDownloadExtracted = useCallback(async (response: { ok: boolean; extracted: Record<string, unknown>; missing: string[]; ocr_used: boolean; raw_text_preview?: string }) => {
    try {
      const wsData = [
        ['录波记录厂站', '故障时刻', '故障线路名称', '故障相', '故障持续时间(ms)', '重合闸情况', '故障相电压', '故障相电流', '最大零序电流(A)', '零序补偿系数K', '线路总长度L(km)', '线路正序灵敏角(°)', '线路正序阻抗定值(Ω)'],
        [
          response.extracted.station ?? '',
          response.extracted.fault_time ?? '',
          response.extracted.line_name ?? '',
          response.extracted.fault_phase ?? '',
          response.extracted.duration_ms ?? '',
          response.extracted.reclosing ?? '',
          response.extracted.phase_voltage ?? '',
          response.extracted.phase_current ?? '',
          response.extracted.zero_sequence_current ?? '',
          response.extracted.zero_sequence_compensation_k ?? '',
          response.extracted.line_length_km ?? '',
          response.extracted.sensitive_angle_deg ?? '',
          response.extracted.positive_sequence_impedance_ohm ?? '',
        ]
      ];
      // xlsx（SheetJS，约 400KB）按需动态加载：仅在实际导出录波结果时下载该 chunk
      const XLSX = await import("xlsx");
      const ws = XLSX.utils.aoa_to_sheet(wsData);
      ws['!cols'] = wsData[0].map(() => ({ wch: 22 }));
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, '录波提取');
      XLSX.writeFile(wb, '录波提取结果.xlsx');
    } catch {
      messageApi.error('下载录波提取结果失败');
    }
  }, []);
  // 下载录波数据模板（13 个字段，与分析程序实际使用的录波故障数据一致；填写后上传可自动回填）
  const handleDownloadWaveDataTemplate = () => {
    try {
      generateWaveDataTemplate();
      messageApi.success('录波数据模板下载成功');
    } catch {
      messageApi.error('录波数据模板下载失败');
    }
  };

  // 下载雷电定位数据模板
  const handleDownloadLightningTemplate = () => {
    try {
      generateLightningTemplate();
      messageApi.success('雷电定位数据模板下载成功');
    } catch {
      messageApi.error('雷电定位数据模板下载失败');
    }
  };

  // 下载行波数据模板
  const handleDownloadWaveTemplate = () => {
    try {
      generateWaveTemplate();
      messageApi.success('行波数据模板下载成功');
    } catch {
      messageApi.error('行波数据模板下载失败');
    }
  };

  // 下载光学监控数据模板
  const handleDownloadOpticalTemplate = () => {
    try {
      generateOpticalTemplate();
      messageApi.success('光学监控数据模板下载成功');
    } catch {
      messageApi.error('光学监控数据模板下载失败');
    }
  };

  // LP-420：文件字段 + 对应 previewKind 映射
  const FILE_KIND_MAP: Array<{
    field: keyof Pick<
      CreateFaultAnalysisFormValues,
      "wave_data_file" | "lightning_data_file" | "ledger_data_file" | "traveling_wave_file" | "optical_data_file"
    >;
    kind: "wave_data" | "lightning_data" | "ledger_data" | "traveling_wave" | "optical_data";
    label: string;
  }> = [
    { field: "wave_data_file", kind: "wave_data", label: t("录波数据") },
    { field: "lightning_data_file", kind: "lightning_data", label: t("雷电定位数据") },
    { field: "ledger_data_file", kind: "ledger_data", label: t("判别台账") },
    { field: "traveling_wave_file", kind: "traveling_wave", label: t("分布式行波数据") },
    { field: "optical_data_file", kind: "optical_data", label: t("光学监控数据") },
  ];

  // LP-420：提交前置内容校验汇总
  const handleFinish = () => {
    // 步骤切换后同位置按钮由「下一步」替换为「提交」，快速连点的第二次点击
    // 可能落在「提交」上误触发创建（弹窗随之关闭），忽略切换后极短窗口内的提交。
    if (Date.now() - lastStepChangeAtRef.current < 350) {
      return;
    }
    // 分步表单提交时 onFinish 的 values 只包含「当前步骤已挂载」的字段（rc-field-form
    // validateFields → getFieldsValue(namePathList) 只收集已注册字段），第一步/第二步的
    // 值（任务名称、线路、故障信息、录波文件）会被丢掉，导致创建请求缺失标量字段与
    // 录波文件、判别程序收到空录波输入（已复现）。改用 getFieldsValue(true) 取完整 store。
    const values = form.getFieldsValue(true) as CreateFaultAnalysisFormValues;
    const allErrors: string[] = [];
    const allWarnings: string[] = [];
    const pendingChecks: Array<{ files: FaultAnalysisTempFile[]; label: string }> = [];

    for (const { field, kind, label } of FILE_KIND_MAP) {
      const files = values[field] ?? [];
      if (files.length === 0) {
        continue;
      }
      // 录波文件由后端 extract-wave 做识别提取（不走本地 startValidate，因此没有 preview）；
      // 只有仍在提取中（pdfExtracting）才算「在解析中」需要提示，提取完成即可正常提交。
      if (kind === "wave_data") {
        if (files.some((f) => f.pdfExtracting)) {
          pendingChecks.push({ files, label });
        }
        continue;
      }
      const filesWithPreview = files.filter((f) => !!f.preview);
      const filesWithoutPreview = files.filter((f) => !f.preview);
      if (filesWithoutPreview.length > 0) {
        pendingChecks.push({ files, label });
        continue;
      }
      for (const file of filesWithPreview) {
        for (const err of file.preview?.errors ?? []) {
          allErrors.push(`【${label}】${file.name}：${err}`);
        }
        for (const warn of file.preview?.warnings ?? []) {
          allWarnings.push(`【${label}】${file.name}：${warn}`);
        }
      }
    }

    if (pendingChecks.length > 0) {
      modalApi.confirm({
        title: t("部分文件尚未完成内容校验"),
        content: `${pendingChecks.map((p) => p.label).join("、")} 仍有文件在解析中或尚未校验，确定要提交吗？`,
        okText: t("仍要提交"),
        cancelText: t("等待校验"),
        onOk: () => onSubmit(values),
      });
      return;
    }

    if (allErrors.length > 0) {
      modalApi.confirm({
        title: t("以下文件存在格式错误，无法参与判别"),
        content: (
          <div className="max-h-[300px] overflow-y-auto">
            {allErrors.map((err, i) => (
              <div key={i} className="mb-1 text-red-600">
                {err}
              </div>
            ))}
            <div className="mt-2 text-gray-500">{t("请移除对应文件后重新提交。")}</div>
          </div>
        ),
        okText: t("我知道了"),
        cancelButtonProps: { style: { display: "none" } },
        onOk: () => {},
      });
      return;
    }

    if (allWarnings.length > 0) {
      modalApi.confirm({
        title: t("部分文件疑似缺少字段"),
        content: (
          <div className="max-h-[300px] overflow-y-auto">
            {allWarnings.slice(0, 10).map((w, i) => (
              <div key={i} className="mb-1 text-yellow-600">
                {w}
              </div>
            ))}
            {allWarnings.length > 10 && <div className="mt-1 text-gray-500">...等共 {allWarnings.length} 条提示</div>}
            <div className="mt-2 text-gray-500">{t("仍要提交吗？")}</div>
          </div>
        ),
        okText: t("仍要提交"),
        cancelText: t("返回修改"),
        onOk: () => onSubmit(values),
      });
      return;
    }

    onSubmit(values);
  };

  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={handleFinish}
      className="admin-fault-analysis-form-tabs"
    >
      {/* 分步配置进度条（参照防雷计算任务新建表单） */}
      <Steps
        current={currentStep}
        size="small"
        className="mb-4"
        items={STEP_TITLES.map((title, index) => ({ title: t(title), key: index }))}
      />

      {/* 步骤内容区：撑满抽屉剩余高度，超高时内部滚动（顶部步骤栏 / 底部按钮栏固定不滚动） */}
      <div className="admin-fault-analysis-form-scroll">
        {/* 第 1 步：故障线路 */}
        {currentStep === 0 ? (
          <div className="admin-fault-analysis-form-section">
            <div className="px-1">
              <Form.Item
                label={t("任务名称")}
                name="title"
                rules={[{ required: true, message: t("请输入任务名称") }]}
              >
                <Input placeholder={t("例如：XX线路故障分析")} maxLength={100} />
              </Form.Item>
              <Form.Item
                label={t("故障线路")}
                name="line_id"
                rules={[{ required: true, message: t("请选择故障线路") }]}
              >
                <Select
                  placeholder={t("请选择故障线路名称")}
                  loading={linesLoading}
                  showSearch
                  optionFilterProp="children"
                  filterOption={(input, option) =>
                    (option?.label ?? "").toLowerCase().includes(input.toLowerCase())
                  }
                  options={lines.map((line) => ({
                    value: line.id,
                    label: `${line.name} (${line.code})`,
                  }))}
            />
          </Form.Item>
        </div>

        {/* 选中线路后展示该线路杆塔列表（参照防雷计算任务新建表单）；标题沿用上方表单项的 label 样式 */}
        {selectedLineId ? (
          <div className="px-1 mt-3">
            <Form.Item label={t("线路杆塔")}>
              {towersQuery.isError ? (
                <Alert
                  type="error"
                  showIcon
                  message={t("杆塔列表加载失败")}
                  description={towersQuery.error instanceof Error ? towersQuery.error.message : t("未知错误")}
                />
              ) : (
                <Table<LineTowerSummary>
                  rowKey={(row) => row.id}
                  columns={towerColumns}
                  dataSource={towersQuery.data?.items ?? []}
                  loading={towersQuery.isFetching}
                  size="small"
                  pagination={{
                    current: towerPage,
                    pageSize: TOWER_PAGE_SIZE,
                    total: towersQuery.data?.total ?? 0,
                    showSizeChanger: false,
                    hideOnSinglePage: true,
                    onChange: (page) => setTowerPage(page),
                  }}
                  scroll={{ x: 760 }}
                />
              )}
            </Form.Item>
          </div>
        ) : null}
      </div>
        ) : null}

        {/* 第 2 步：故障信息 */}
        {currentStep === 1 ? (
        <div className="admin-fault-analysis-form-section">
        <div className="space-y-4 px-1">

          {/* 录波数据上传（置于第二步顶部）：上传 PDF 自动识别并直接回填下方故障信息字段 */}
          <div className="border border-[var(--gray-6)] rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-[var(--gray-2)] min-h-[160px]">
            <FileTextOutlined className="text-4xl text-[var(--ant-color-primary)]" />
            <div className="text-center">
              <div className="font-semibold text-sm mb-1">{t("录波数据")}</div>
              <div className="text-xs text-gray-500 mb-3">{t("支持 .txt/.json/.csv/.pdf/.xlsx，上传后自动识别并回填下方故障信息")}</div>
            </div>
            <Form.Item name="wave_data_file" className="mb-0">
              <TempFileUpload
                accept=".txt,.json,.csv,.pdf,.xlsx"
                maxSizeMb={50}
                buttonLabel={t("选择文件")}
                previewKind="wave_data"
                trailing={
                  <Button size="small" icon={<DownloadOutlined />} onClick={handleDownloadWaveDataTemplate}>
                    {t("下载模板")}
                  </Button>
                }
                onPdfExtracted={(item, response) => {
                  handlePdfExtracted(item, response);
                  if (response.missing.length === 13) {
                    messageApi.warning('未识别到故障字段：请使用「下载模板」的格式（录波记录厂站/故障时刻/故障线路名称等表头）或上传录波故障报告 PDF');
                  } else if (response.ok) {
                    messageApi.success('已自动提取并回填表单字段');
                  } else {
                    messageApi.success(`已识别 ${13 - response.missing.length}/13 个字段，缺失字段已提示`);
                  }
                }}
              />
            </Form.Item>
            {extractState && extractState.response.extracted && (
              <div className="mt-1 w-full rounded bg-[var(--ant-color-primary-bg)] px-2 py-1 text-xs text-[var(--ant-color-text)]">
                <div className="flex items-center justify-between">
                  <span>
                    识别到 {13 - extractState.response.missing.length}/13 个字段
                    {extractState.response.missing.length > 0 && (
                      <span className="ml-1 text-[var(--orange-9)]">（缺失 {extractState.response.missing.length} 个）</span>
                    )}
                  </span>
                  <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownloadExtracted(extractState.response)}>
                    {t("下载 Excel")}
                  </Button>
                </div>
                {extractState.response.missing.length > 0 && (
                  <div className="mt-1 text-yellow-600">
                    {t("缺失字段")}：{extractState.response.missing.map((key) => t(WAVE_FIELD_LABELS[key] ?? key)).join("、")}
                  </div>
                )}
              </div>
            )}
          </div>

          <Form.Item
            label={t("录波记录厂站")}
            name="station_name"
            rules={[{ required: true, message: t("请输入录波记录厂站") }]}
          >
            <Input placeholder={t("广东河源500kV上寨变")} />
          </Form.Item>

          <Space.Compact className="w-full">
            <Form.Item
              label={t("故障时刻")}
              name="fault_time"
              className="flex-1 mb-0"
              rules={[{ required: true, message: t("请输入故障时刻") }]}
            >
              <Input placeholder="2023-03-27 20:20:31.939" />
            </Form.Item>
            <div className="w-5" />
            <Form.Item
              label={t("故障线路名称")}
              name="fault_line_name"
              className="flex-1 mb-0"
              rules={[{ required: true, message: t("请输入故障线路名称") }]}
            >
              <Input placeholder={t("220kV 龙和线")} />
            </Form.Item>
          </Space.Compact>

          <Space.Compact className="w-full">
            <Form.Item
              label={t("故障相")}
              name="fault_phase"
              className="flex-1 mb-0"
              rules={[{ required: true, message: t("请选择故障相") }]}
            >
              <Select
                placeholder="A/B/C/AN/BN/CN/AB/BC/AC/ABC/ABN/BCN/ACN"
                options={[
                  { value: "A", label: "A" },
                  { value: "B", label: "B" },
                  { value: "C", label: "C" },
                  { value: "AN", label: "AN" },
                  { value: "BN", label: "BN" },
                  { value: "CN", label: "CN" },
                  { value: "AB", label: "AB" },
                  { value: "BC", label: "BC" },
                  { value: "AC", label: "AC" },
                  { value: "ABC", label: "ABC" },
                  { value: "ABN", label: "ABN" },
                  { value: "BCN", label: "BCN" },
                  { value: "ACN", label: "ACN" },
                ]}
              />
            </Form.Item>
            <div className="w-5" />
            <Form.Item
              label={t("故障持续时间(ms)")}
              name="fault_duration"
              className="flex-1 mb-0"
              rules={[]}
            >
              <Input type="number" placeholder="64" />
            </Form.Item>
          </Space.Compact>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label={t("重合闸情况")}
              name="reclosure_status"
              className="mb-0"
              rules={[{ required: true, message: t("请选择重合闸情况") }]}
            >
              <Select
                placeholder={t("成功")}
                options={[
                  { value: "success", label: t("成功") },
                  { value: "failed", label: t("失败") },
                  { value: "not_applicable", label: t("不适用") },
                ]}
              />
            </Form.Item>
            <Form.Item
              label={t("故障相电压(V)")}
              name="fault_voltage"
              className="mb-0"
            >
              <Input type="number" placeholder="37.04" />
            </Form.Item>
            <Form.Item
              label={t("故障相电流(A)")}
              name="fault_current"
              className="mb-0"
            >
              <Input type="number" placeholder="1.3" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label={t("最大零序电流(A)")}
              name="max_zero_current"
              className="mb-0"
            >
              <Input type="number" placeholder="1.45" />
            </Form.Item>
            <Form.Item
              label={t("零序补偿系数K")}
              name="zero_compensation"
              className="mb-0"
            >
              <Input type="number" placeholder="0.52" />
            </Form.Item>
            <Form.Item
              label={t("故障电阻Rm(Ω)")}
              name="fault_resistance"
              className="mb-0"
            >
              <Input type="number" placeholder="0.883" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label={t("线路总长度L(km)")}
              name="line_length"
              className="mb-0"
            >
              <Input type="number" placeholder="89.77" />
            </Form.Item>
            <Form.Item
              label={t("线路正序灵敏角(°)")}
              name="line_angle"
              className="mb-0"
            >
              <Input type="number" placeholder="85" />
            </Form.Item>
            <Form.Item
              label={t("线路正序阻抗定值(Ω)")}
              name="line_impedance"
              className="mb-0"
            >
              <Input type="number" placeholder="28.520" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label={t("雷电流幅值I(kA)")}
              name="lightning_current"
              className="mb-0"
            >
              <Input placeholder={t("无/20.3kA")} />
            </Form.Item>
            <Form.Item
              label={t("雷电定位经度(°)")}
              name="lightning_longitude"
              className="mb-0"
            >
              <Input type="number" placeholder={t("无/114.50476")} />
            </Form.Item>
            <Form.Item
              label={t("雷电定位纬度(°)")}
              name="lightning_latitude"
              className="mb-0"
            >
              <Input type="number" placeholder={t("无/23.79996")} />
            </Form.Item>
          </div>

          <Space.Compact className="w-full">
            <Form.Item
              label={t("录波测距(km)")}
              name="wave_distance"
              className="flex-1 mb-0"
            >
              <Input type="number" placeholder="16.022" />
            </Form.Item>
            <div className="w-5" />
            <Form.Item
              label={t("行波测距(km)")}
              name="traveling_wave_distance"
              className="flex-1 mb-0"
            >
              <Input type="number" placeholder="16.51" />
            </Form.Item>
          </Space.Compact>

          <Space.Compact className="w-full">
            <Form.Item
              label={t("光学接闪位置(绕击/反击/分叉)")}
              name="optical_position"
              className="flex-1 mb-0"
            >
              <Input placeholder={t("无/A/B/C/G/AB/BC/AC/AG/BG/CG/AN/BN/CN")} />
            </Form.Item>
            <div className="w-5" />
            <Form.Item
              label={t("光学设备安装位置")}
              name="optical_device_location"
              className="flex-1 mb-0"
            >
              <Input placeholder="65#" />
            </Form.Item>
          </Space.Compact>
        </div>
      </div>
        ) : null}

        {/* 第 3 步：分析数据 */}
        {currentStep === 2 ? (
        <div className="admin-fault-analysis-form-section">
        <div className="px-1 space-y-4">
          <div className="grid grid-cols-1 gap-4">
            <div className="border border-[var(--gray-6)] rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-[var(--gray-2)] min-h-[160px]">
              <TableOutlined className="text-4xl text-[var(--ant-color-primary)]" />
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">{t("雷电定位数据")}</div>
                <div className="text-xs text-gray-500 mb-3">{t("支持 .xls/.xlsx/.csv 格式")}</div>
              </div>
              <Form.Item name="lightning_data_file" className="mb-0">
                <TempFileUpload
                  accept=".xls,.xlsx,.csv"
                  maxSizeMb={50}
                  buttonLabel={t("选择文件")}
                  previewKind="lightning_data"
                  trailing={
                    <Button size="small" icon={<DownloadOutlined />} onClick={handleDownloadLightningTemplate}>
                      {t("下载模板")}
                    </Button>
                  }
                />
              </Form.Item>
            </div>

            <div className="border border-[var(--gray-6)] rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-[var(--gray-2)] min-h-[160px]">
              <LineChartOutlined className="text-4xl text-[var(--ant-color-primary)]" />
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">{t("分布式行波数据")}</div>
                <div className="text-xs text-gray-500 mb-3">{t("支持 .csv/.dat/.txt/.json 格式，可多选（A/B/C 三相）")}</div>
              </div>
              <Form.Item name="traveling_wave_file" className="mb-0">
                <TempFileUpload
                  accept=".csv,.dat,.txt,.json"
                  maxSizeMb={50}
                  buttonLabel={t("选择文件")}
                  previewKind="traveling_wave"
                  multiple
                  trailing={
                    <Button size="small" icon={<DownloadOutlined />} onClick={handleDownloadWaveTemplate}>
                      {t("下载模板")}
                    </Button>
                  }
                />
              </Form.Item>
            </div>

            <div className="border border-[var(--gray-6)] rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-[var(--gray-2)] min-h-[160px]">
              <CameraOutlined className="text-4xl text-[var(--ant-color-primary)]" />
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">{t("光学监控数据")}</div>
                <div className="text-xs text-gray-500 mb-3">{t("支持图片或视频格式")}</div>
              </div>
              <Form.Item name="optical_data_file" className="mb-0">
                <TempFileUpload
                  accept="image/*,video/*"
                  maxSizeMb={50}
                  buttonLabel={t("选择文件")}
                  previewKind="optical_data"
                  trailing={
                    <Button size="small" icon={<DownloadOutlined />} onClick={handleDownloadOpticalTemplate}>
                      {t("下载模板")}
                    </Button>
                  }
                />
              </Form.Item>
            </div>

          </div>
        </div>
      </div>
        ) : null}
      </div>

      {/* 底部导航：上一步 / 下一步 / 提交，固定在抽屉右下角（取消按钮已移除，关闭走抽屉右上角 X / 遮罩） */}
      <div className="admin-fault-analysis-form-actions">
        {currentStep > 0 ? (
          <Button onClick={goPrev} disabled={submitting}>
            {t("上一步")}
          </Button>
        ) : null}
        {currentStep < lastStepIndex ? (
          <Button type="primary" onClick={goNext}>
            {t("下一步")}
          </Button>
        ) : (
          <Button type="primary" htmlType="submit" loading={submitting}>
            {submitText}
          </Button>
        )}
      </div>
    </Form>
  );
}
