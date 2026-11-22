import * as XLSX from 'xlsx';
import type { CreateFaultAnalysisFormValues } from '@/components/fault-analysis/types';

/**
 * Excel导入字段映射配置
 */
const FIELD_MAPPING = {
  '录波记录厂站': 'station_name',
  '故障时刻': 'fault_time',
  '故障线路名称': 'fault_line_name',
  '故障相': 'fault_phase',
  '故障持续时间(ms)': 'fault_duration',
  '重合闸情况': 'reclosure_status',
  '故障相电压(V)': 'fault_voltage',
  '故障相电流(A)': 'fault_current',
  '最大零序电流(A)': 'max_zero_current',
  '零序补偿系数K': 'zero_compensation',
  '故障电阻Rm(Ω)': 'fault_resistance',
  '线路总长度L(km)': 'line_length',
  '线路正序灵敏角(°)': 'line_angle',
  '线路正序阻抗定值(Ω)': 'line_impedance',
  '雷电流幅值I(kA)': 'lightning_current',
  '雷电定位经度(°)': 'lightning_longitude',
  '雷电定位纬度(°)': 'lightning_latitude',
  '录波测距(km)': 'wave_distance',
  '行波测距(km)': 'traveling_wave_distance',
  '光学接闪位置': 'optical_position',
  '光学设备安装位置': 'optical_device_location',
} as const;

/**
 * 重合闸情况映射
 */
const RECLOSURE_MAPPING: Record<string, string> = {
  '成功': 'success',
  '失败': 'failed',
  '不适用': 'not_applicable',
};

/**
 * 从Excel文件解析故障信息数据
 */
export async function parseExcelFile(file: File, t: (s: string) => string = (s) => s): Promise<Partial<CreateFaultAnalysisFormValues>> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = (e) => {
      try {
        const data = e.target?.result;
        if (!data) {
          throw new Error(t('读取文件失败'));
        }

        const workbook = XLSX.read(data, { type: 'binary' });
        const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
        const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 }) as any[][];

        if (jsonData.length < 2) {
          throw new Error(t('Excel文件格式不正确，至少需要包含表头和一行数据'));
        }

        // 第一行为表头，第二行为数据
        const headers = jsonData[0] as string[];
        const values = jsonData[1];

        const formData: Partial<CreateFaultAnalysisFormValues> = {};

        // 遍历表头，根据映射关系提取数据
        headers.forEach((header, index) => {
          const fieldName = FIELD_MAPPING[header as keyof typeof FIELD_MAPPING];
          if (fieldName && values[index] !== undefined && values[index] !== null && values[index] !== '') {
            let value = values[index];

            // 数据类型转换
            if (fieldName === 'fault_duration' ||
                fieldName === 'fault_voltage' ||
                fieldName === 'fault_current' ||
                fieldName === 'max_zero_current' ||
                fieldName === 'zero_compensation' ||
                fieldName === 'fault_resistance' ||
                fieldName === 'line_length' ||
                fieldName === 'line_angle' ||
                fieldName === 'line_impedance' ||
                fieldName === 'lightning_longitude' ||
                fieldName === 'lightning_latitude' ||
                fieldName === 'wave_distance' ||
                fieldName === 'traveling_wave_distance') {
              // 数值类型
              value = typeof value === 'number' ? value : parseFloat(value);
              if (!isNaN(value)) {
                (formData as any)[fieldName] = value;
              }
            } else if (fieldName === 'reclosure_status') {
              // 重合闸情况映射
              const mappedValue = RECLOSURE_MAPPING[value] || value;
              (formData as any)[fieldName] = mappedValue;
            } else {
              // 字符串类型
              (formData as any)[fieldName] = String(value);
            }
          }
        });

        resolve(formData);
      } catch (error) {
        reject(error);
      }
    };

    reader.onerror = () => {
      reject(new Error(t('读取文件失败')));
    };

    reader.readAsBinaryString(file);
  });
}

/**
 * 生成导入模板Excel文件
 */
export function generateImportTemplate() {
  // 表头
  const headers = Object.keys(FIELD_MAPPING);

  // 示例数据
  const exampleData = [
    '广东河源500kV上寨变',
    '2023-03-27 20:20:31.939',
    '220kV 龙和线',
    'AN',
    '64',
    '成功',
    '37.04',
    '1.3',
    '1.45',
    '0.52',
    '0.883',
    '89.77',
    '85',
    '28.520',
    '20.3',
    '114.50476',
    '23.79996',
    '16.022',
    '16.51',
    'A',
    '65#',
  ];

  // 创建工作表数据
  const wsData = [headers, exampleData];

  // 创建工作表
  const ws = XLSX.utils.aoa_to_sheet(wsData);

  // 设置列宽
  const colWidths = headers.map(() => ({ wch: 20 }));
  ws['!cols'] = colWidths;

  // 创建工作簿
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '故障信息模板');

  // 导出文件
  XLSX.writeFile(wb, '故障信息导入模板.xlsx');
}

/**
 * 生成录波数据模板（与分析程序实际使用的录波故障数据一致：13 个字段，表头与后端识别别名匹配）
 */
export function generateWaveDataTemplate() {
  const headers = [
    '录波记录厂站',
    '故障时刻',
    '故障线路名称',
    '故障相',
    '故障持续时间(ms)',
    '重合闸情况',
    '故障相电压',
    '故障相电流',
    '最大零序电流(A)',
    '零序补偿系数K',
    '线路总长度L(km)',
    '线路正序灵敏角(°)',
    '线路正序阻抗定值(Ω)',
  ];

  const exampleData = [
    '广东河源500kV上寨变',
    '2023-03-27 20:20:31.939',
    '220kV 龙和线',
    'A',
    '64',
    '成功',
    '37.04',
    '1.3',
    '1.45',
    '0.52',
    '120.5',
    '76.2',
    '18.35',
  ];

  const wsData = [headers, exampleData];
  const ws = XLSX.utils.aoa_to_sheet(wsData);

  const colWidths = headers.map(() => ({ wch: 20 }));
  ws['!cols'] = colWidths;

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '录波数据模板');

  XLSX.writeFile(wb, '录波数据模板.xlsx');
}

/**
 * 生成雷电定位数据模板
 *
 * `headersOverride` 用于需要特定表头口径的场景（如风电场地闪密度统计要求
 * `经度` / `纬度` 精确匹配，见 `generateWindLightningTemplate`）；不传保持原默认表头。
 */
export function generateLightningTemplate(headersOverride?: string[]) {
  const headers = headersOverride ?? ['时间', '经度(°)', '纬度(°)', '雷电流幅值(kA)', '极性', '距离(km)'];

  const exampleData = [
    '2023-03-27 20:20:30',
    '114.50476',
    '23.79996',
    '20.3',
    '负',
    '1.2',
  ];

  const wsData = [headers, exampleData];
  const ws = XLSX.utils.aoa_to_sheet(wsData);

  const colWidths = headers.map(() => ({ wch: 20 }));
  ws['!cols'] = colWidths;

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '雷电定位数据模板');

  XLSX.writeFile(wb, '雷电定位数据模板.xlsx');
}

/**
 * 生成风机点位数据模板（风电场地闪密度统计 / 数据准备通用）。
 *
 * 表头与 file_2 口径一致：经度、纬度两列是该页解析所必需，其余列便于同一张表复用到数据准备模块。
 */
export function generateWindTurbineTemplate() {
  const headers = ['风机编号', '经度', '纬度', '输入高程(m)', '风机高度(m)', '叶片长度(m)', '动静状态', '回路编号'];

  const exampleData = ['1', '114.50476', '23.79996', '50', '90', '45', '1', '1'];

  const wsData = [headers, exampleData];
  const ws = XLSX.utils.aoa_to_sheet(wsData);

  const colWidths = headers.map(() => ({ wch: 18 }));
  ws['!cols'] = colWidths;

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '风机点位模板');

  XLSX.writeFile(wb, '风机点位模板.xlsx');
}

/**
 * 生成风电场地闪密度统计的雷电定位模板（CSV）。
 *
 * 后端 `wind_grid.parse_lightning_csv` 只接受 CSV，并按 `经度` / `纬度` / `时间`
 * 精确匹配表头（带 `(°)` 会被判为缺少经纬度列）。因此这里输出 UTF-8 BOM 的 CSV、
 * 文件名用 `.csv`，保证下载后可直接拖回「雷电定位 CSV」上传组件并解析。
 */
export function generateWindLightningTemplate() {
  const content =
    '\uFEFF' +
    '时间,经度,纬度,雷电流幅值(kA),极性,距离(km)\n' +
    '2020-06-01 12:00:00,114.498,23.793,12,负,0.8\n' +
    '2020-07-15 08:30:00,114.501,23.796,-18,负,0.5\n' +
    '2021-05-20 16:10:00,114.503,23.798,25,正,0.3\n' +
    '2021-08-02 09:45:00,114.505,23.800,-30,负,0.2\n' +
    '2022-04-11 14:20:00,114.507,23.802,16,负,0.4\n' +
    '2022-09-08 11:05:00,114.509,23.804,-22,负,0.6\n' +
    '2023-06-30 19:15:00,114.502,23.805,14,正,0.7\n' +
    '2023-08-18 07:50:00,114.506,23.795,-28,负,0.9\n' +
    '2024-05-05 13:30:00,114.500,23.801,20,正,0.4\n' +
    '2024-07-22 10:10:00,114.511,23.799,-35,负,1.0\n';

  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = '雷电定位数据模板.csv';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * 生成行波数据模板
 */
export function generateWaveTemplate() {
  const content =
    '时间,行波幅值(mV),持续时间(us),距离(km)\n' +
    '2023-03-27 20:20:31.939,12.34,5.6,16.51\n';

  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = '行波数据模板.txt';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * 生成光学监控数据模板
 */
export function generateOpticalTemplate() {
  const headers = ['时间', '设备编号', '接闪位置', '安装位置', '状态'];

  const exampleData = [
    '2023-03-27 20:20:31.939',
    'DEV-001',
    'A',
    '65#',
    '正常',
  ];

  const wsData = [headers, exampleData];
  const ws = XLSX.utils.aoa_to_sheet(wsData);

  const colWidths = headers.map(() => ({ wch: 20 }));
  ws['!cols'] = colWidths;

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '光学监控模板');

  XLSX.writeFile(wb, '光学监控模板.xlsx');
}
