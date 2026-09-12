export type PreviewKind = "wave_data" | "lightning_data" | "ledger_data" | "traveling_wave" | "optical_data";

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
  fields: Record<string, boolean>;
  extra?: Record<string, unknown>;
}

const FAULT_FIELD_ALIASES: Record<string, string[]> = {
  station: ["station", "录波记录厂站", "厂站名称"],
  fault_time: ["fault_time", "故障时刻", "故障时间", "故障开始时间"],
  line_name: ["line_name", "故障线路名称", "故障线路", "线路名称"],
  fault_phase: ["fault_phase", "故障相", "故障相别"],
  duration_ms: ["duration_ms", "故障持续时间(ms)", "故障持续时间"],
  reclosing: ["reclosing", "重合闸情况", "重合闸"],
  phase_voltage: ["phase_voltage", "故障相电压", "故障相电压(V)"],
  phase_current: ["phase_current", "故障相电流", "故障相电流(A)"],
  zero_sequence_current: ["zero_sequence_current", "最大零序电流(A)", "最大零序电流", "零序电流", "I0", "3I0"],
  zero_sequence_compensation_k: ["zero_sequence_compensation_k", "零序补偿系数K", "零序电抗补偿系数"],
  line_length_km: ["line_length_km", "线路总长度L(km)", "线路总长度L（km）", "线路总长度"],
  sensitive_angle_deg: ["sensitive_angle_deg", "线路正序灵敏角(°)", "线路正序灵敏角°", "线路正序灵敏角"],
  positive_sequence_impedance_ohm: [
    "positive_sequence_impedance_ohm",
    "线路正序阻抗定值(Ω)",
    "线路正序阻抗定值（Ω）",
    "线路正序阻抗定值",
  ],
};

const LIGHTNING_FIELD_ALIASES: Record<string, string[]> = {
  event_id: ["event_id", "事件编号", "故障编号"],
  line_name: ["line_name", "线路名称", "故障线路名称"],
  fault_time: ["fault_time", "故障时刻", "故障时间"],
  query_result: ["query_result", "是否存在落雷记录", "雷电定位查询结果"],
  location_time: ["location_time", "雷电定位时刻", "落雷时刻"],
  current_ka: ["current_ka", "雷电流幅值(kA)", "雷电流幅值（kA）", "雷电流幅值I(kA)", "雷电流幅值"],
  nearest_tower: ["nearest_tower", "雷电定位最近杆塔", "雷电定位最近杆塔号", "最近杆塔"],
  distance_to_line_km: ["distance_to_line_km", "雷击点距线路距离(km)", "雷击点距线路距离（km）", "距线路距离(km)"],
  distance_to_nearest_tower_m: [
    "distance_to_nearest_tower_m",
    "雷击点距最近杆塔距离(m)",
    "雷击点距最近杆塔距离（m）",
    "距最近杆塔距离(m)",
  ],
  line_side_distances_km: ["line_side_distances_km", "线路两侧距离(km)", "线路两侧距离（km）"],
  recording_distance_km: ["recording_distance_km", "录波测距(km)", "录波测距（km）", "录波测距"],
  recording_nearest_tower: ["recording_nearest_tower", "录波测距最近杆塔", "录波测距最近杆塔号"],
  traveling_wave_distance_km: ["traveling_wave_distance_km", "行波测距(km)", "行波测距（km）", "行波测距"],
  traveling_wave_nearest_tower: ["traveling_wave_nearest_tower", "行波测距最近杆塔", "行波测距最近杆塔号"],
  remarks: ["remarks", "数据来源/备注", "备注"],
};

const LEDGER_OUTPUT_FIELDS: Record<string, string> = {
  "线路名称": "line_name",
  "电压等级": "voltage_level_kv",
  "塔号": "tower_no",
  "地形": "terrain",
  "地闪密度": "ground_flash_density",
  "海拔m": "elevation_m",
  "杆塔模型": "tower_model",
  "塔形": "tower_shape",
  "直线或耐张杆塔": "tower_function",
  "绝缘子串长度mm": "insulator_length_mm",
  "接地电阻": "ground_resistance_ohm",
  "反击耐雷水平kA": "backflashover_withstand_ka",
  "绕击耐雷水平kA": "shielding_failure_withstand_ka",
  "雷击风险等级": "lightning_risk_level",
  "经度": "longitude",
  "纬度": "latitude",
};

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("读取文件失败"));
    reader.readAsText(file);
  });
}

function readFileAsArrayBuffer(file: File): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(new Error("读取文件失败"));
    reader.readAsArrayBuffer(file);
  });
}

function splitCsvLine(line: string): string[] {
  const result: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === "," && !inQuotes) {
      result.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
  }
  result.push(current.trim());
  return result;
}

function normalizeHeader(name: string): string {
  return String(name).replace(/\s+/g, "").replace(/[（）\(\)]/g, function (match) {
    return { "（": "(", "）": ")", "(": "(", ")": ")" }[match] || match;
  });
}

function matchAliases(header: string, aliases: Record<string, string[]>): { key: string; matched: boolean } {
  const norm = normalizeHeader(header);
  for (const [key, values] of Object.entries(aliases)) {
    for (const alias of values) {
      if (norm === alias) return { key, matched: true };
    }
  }
  return { key: "", matched: false };
}

function buildWaveFieldStatus(headers: string[]): Record<string, boolean> {
  const fields: Record<string, boolean> = {};
  for (const header of headers) {
    const { key, matched } = matchAliases(header, FAULT_FIELD_ALIASES);
    if (matched) {
      fields[key] = true;
    }
  }
  return fields;
}

function buildLightningFieldStatus(headers: string[]): Record<string, boolean> {
  const fields: Record<string, boolean> = {};
  for (const header of headers) {
    const { key, matched } = matchAliases(header, LIGHTNING_FIELD_ALIASES);
    if (matched) {
      fields[key] = true;
    }
  }
  return fields;
}

async function readXlsxHeaders(file: File): Promise<string[]> {
  // xlsx（SheetJS，约 400KB）按需动态加载：只在真正选中 xlsx 文件时下载该 chunk
  const XLSX = await import("xlsx");
  const buffer = await readFileAsArrayBuffer(file);
  const workbook = XLSX.read(buffer, { type: "array" });
  const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
  const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 }) as any[][];
  const row = jsonData[0];
  if (!row || row.length === 0) return [];
  return row.map((cell) => String(cell ?? "").trim());
}

async function validateWaveDataFile(file: File): Promise<ValidationResult> {
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  const errors: string[] = [];
  const warnings: string[] = [];
  let fields: Record<string, boolean> = {};
  let extra: Record<string, unknown> = {};

  if (ext === "pdf") {
    try {
      const buffer = await readFileAsArrayBuffer(file);
      const bytes = new Uint8Array(buffer).slice(0, 2048);
      const sample = new TextDecoder("utf-8").decode(bytes);
      const containsChinese = /[\u4e00-\u9fff]/.test(sample);
      const isScannedPdf = sample.includes("%PDF") === false;
      return {
        ok: true,
        errors: [],
        warnings: containsChinese
          ? ["PDF 已识别到文本内容，正在后端自动提取字段并回填表单..."]
          : isScannedPdf
            ? ["PDF 疑似扫描件，文本层不可用，将尝试 OCR 识别，可能较慢"]
            : ["PDF 文本层未识别到中文，将交由后端尝试 OCR 提取"],
        fields: {},
        extra: { format: "pdf", containsChinese, isScannedPdf },
      };
    } catch {
      return {
        ok: true,
        errors: [],
        warnings: ["PDF 无法读取二进制内容，将交由后端尝试提取"],
        fields: {},
        extra: { format: "pdf" },
      };
    }
  }

  if (ext === "xlsx" || ext === "xls") {
    const headers = await readXlsxHeaders(file);
    fields = buildWaveFieldStatus(headers);
    extra = { format: "xlsx", headers };
    return { ok: true, errors, warnings, fields, extra };
  }

  if (ext === "json") {
    try {
      const text = await readFileAsText(file);
      const data = JSON.parse(text);
      if (!Array.isArray(data) && typeof data !== "object") {
        errors.push("JSON 结构不符合录波数据预期格式");
      } else {
        const sample = Array.isArray(data) && data.length > 0 ? data[0] : data;
        const sampleObj = typeof sample === "object" && sample !== null ? sample : {};
        for (const header of Object.keys(sampleObj)) {
          const result = matchAliases(header, FAULT_FIELD_ALIASES);
          if (result.matched) {
            fields[result.key] = true;
          }
        }
      }
    } catch {
      errors.push("JSON 解析失败");
    }
    return { ok: errors.length === 0, errors, warnings, fields, extra };
  }

  if (ext === "csv" || ext === "txt") {
    const text = await readFileAsText(file);
    const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
    if (lines.length === 0) {
      errors.push("文件内容为空");
      return { ok: false, errors, warnings, fields };
    }
    const headers = splitCsvLine(lines[0]);
    fields = buildWaveFieldStatus(headers);
    extra = { format: ext, headers, rowCount: lines.length };
    return { ok: errors.length === 0, errors, warnings, fields, extra };
  }

  errors.push("不支持的文件格式");
  return { ok: false, errors, warnings, fields };
}

async function validateLightningDataFile(file: File): Promise<ValidationResult> {
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  const errors: string[] = [];
  const warnings: string[] = [];
  let fields: Record<string, boolean> = {};
  let extra: Record<string, unknown> = {};

  if (ext === "xlsx" || ext === "xls") {
    const headers = await readXlsxHeaders(file);
    fields = buildLightningFieldStatus(headers);
    extra = { format: "xlsx", headers };
    return { ok: true, errors, warnings, fields, extra };
  }

  if (ext === "csv") {
    const text = await readFileAsText(file);
    const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
    if (lines.length === 0) {
      errors.push("文件内容为空");
      return { ok: false, errors, warnings, fields };
    }
    const headers = splitCsvLine(lines[0]);
    fields = buildLightningFieldStatus(headers);
    extra = { format: "csv", headers, rowCount: lines.length };
    return { ok: errors.length === 0, errors, warnings, fields, extra };
  }

  errors.push("雷电定位数据仅支持 .xlsx/.xls/.csv 格式");
  return { ok: false, errors, warnings, fields };
}

async function validateLedgerDataFile(file: File): Promise<ValidationResult> {
  const errors: string[] = [];
  const warnings: string[] = [];
  const fields: Record<string, boolean> = {};

  const text = await readFileAsText(file);
  const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length === 0) {
    errors.push("台账文件内容为空");
    return { ok: false, errors, warnings, fields };
  }

  const headers = splitCsvLine(lines[0]);
  if (headers.length !== 16) {
    errors.push(`台账列数应为 16，当前识别到 ${headers.length} 列`);
    return { ok: false, errors, warnings, fields };
  }

  const matchedCols = new Set<string>();
  for (const header of headers) {
    for (const [expected, _mapped] of Object.entries(LEDGER_OUTPUT_FIELDS)) {
      if (normalizeHeader(header) === normalizeHeader(expected)) {
        fields[expected] = true;
        matchedCols.add(expected);
      }
    }
  }

  const missingCols = Object.keys(LEDGER_OUTPUT_FIELDS).filter((col) => !matchedCols.has(col));
  if (missingCols.length > 0) {
    warnings.push(`台账缺少必填列：${missingCols.join("、")}`);
  }

  const towerNoIndex = headers.findIndex((h) => normalizeHeader(h) === normalizeHeader("塔号"));
  if (towerNoIndex >= 0) {
    const towerNos: string[] = [];
    for (let i = 1; i < Math.min(lines.length, 1001); i++) {
      const cols = splitCsvLine(lines[i]);
      if (cols[towerNoIndex]) {
        towerNos.push(cols[towerNoIndex]);
      }
    }
    const uniqueTowerNos = new Set(towerNos);
    if (towerNos.length !== uniqueTowerNos.size) {
      warnings.push("塔号存在重复记录，请核对数据");
    }
  }

  return { ok: errors.length === 0, errors, warnings, fields };
}

async function validateTravelingWaveFile(file: File): Promise<ValidationResult> {
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  const errors: string[] = [];
  const warnings: string[] = [];
  let fields: Record<string, boolean> = {};
  let extra: Record<string, unknown> = {};

  if (ext === "json") {
    try {
      const text = await readFileAsText(file);
      const data = JSON.parse(text);
      if (!Array.isArray(data)) {
        errors.push("JSON 根节点应为数组格式");
        return { ok: false, errors, warnings, fields };
      }
      if (data.length < 32) {
        errors.push(`采样点数量不足 32，当前 ${data.length} 点`);
      }
      const sample = data[0];
      if (typeof sample !== "object" || sample === null) {
        errors.push("采样数据格式异常");
      } else {
        const phaseKeys = ["A", "B", "C", "a", "b", "c"];
        const foundPhases = phaseKeys.filter((p) => Object.prototype.hasOwnProperty.call(sample, p));
        if (foundPhases.length === 0) {
          errors.push("未识别到 A/B/C 三相采样数据");
        }
        fields = { phase_count: foundPhases.length === 3 };
      }
      extra = { format: "json", sampleCount: data.length };
      return { ok: errors.length === 0, errors, warnings, fields, extra };
    } catch {
      errors.push("JSON 解析失败");
      return { ok: false, errors, warnings, fields };
    }
  }

  const text = await readFileAsText(file);
  const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
  const dataRowCount = Math.max(lines.length - 1, 0);
  if (lines.length === 0) {
    errors.push("文件内容为空");
    return { ok: false, errors, warnings, fields };
  }
  const headerLine = lines[0] || "";
  const hasPhaseA = /A/.test(headerLine);
  const hasPhaseB = /B/.test(headerLine);
  const hasPhaseC = /C/.test(headerLine);
  if (!hasPhaseA && !hasPhaseB && !hasPhaseC) {
    errors.push("未识别到 A/B/C 相标");
  } else {
    fields = {
      hasPhaseA,
      hasPhaseB,
      hasPhaseC,
      phaseCount: [hasPhaseA, hasPhaseB, hasPhaseC].filter(Boolean).length,
    };
  }
  extra = { format: ext, rowCount: dataRowCount, hasPhaseA, hasPhaseB, hasPhaseC };
  return { ok: errors.length === 0, errors, warnings, fields, extra };
}

async function validateOpticalDataFile(file: File): Promise<ValidationResult> {
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  const isImage = ["jpg", "jpeg", "png", "gif", "bmp", "webp"].includes(ext);
  const isVideo = ["mp4", "avi", "mov", "mkv", "wmv", "flv"].includes(ext);
  if (!isImage && !isVideo) {
    return {
      ok: false,
      errors: ["光学监控数据仅支持图片或视频格式"],
      warnings: [],
      fields: {},
      extra: { format: ext },
    };
  }
  return {
    ok: true,
    errors: [],
    warnings: [],
    fields: { supported: true },
    extra: { format: ext, kind: isImage ? "image" : "video" },
  };
}

export async function validateFile(file: File, kind: PreviewKind): Promise<ValidationResult> {
  switch (kind) {
    case "wave_data":
      return validateWaveDataFile(file);
    case "lightning_data":
      return validateLightningDataFile(file);
    case "ledger_data":
      return validateLedgerDataFile(file);
    case "traveling_wave":
      return validateTravelingWaveFile(file);
    case "optical_data":
      return validateOpticalDataFile(file);
    default:
      return { ok: true, errors: [], warnings: [], fields: {} };
  }
}
