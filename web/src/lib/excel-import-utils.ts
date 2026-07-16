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
export async function parseExcelFile(file: File): Promise<Partial<CreateFaultAnalysisFormValues>> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = (e) => {
      try {
        const data = e.target?.result;
        if (!data) {
          throw new Error('读取文件失败');
        }

        const workbook = XLSX.read(data, { type: 'binary' });
        const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
        const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 }) as any[][];

        if (jsonData.length < 2) {
          throw new Error('Excel文件格式不正确，至少需要包含表头和一行数据');
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
      reject(new Error('读取文件失败'));
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
