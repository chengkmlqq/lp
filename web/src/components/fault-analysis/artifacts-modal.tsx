"use client";

import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Empty, Modal, Space, Spin, Table, Typography } from "antd";
import {
  DownloadOutlined,
  FileExcelOutlined,
  FileTextOutlined,
  PictureOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { FaultAnalysisDetail } from "@/types/auth";

const FAULT_ANALYSIS_KEY_PREFIX = "fault-analysis/";

const { Text } = Typography;

function artifactIcon(key: string): React.ReactNode {
  const name = key.toLowerCase();
  if (name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".bmp")) {
    return <PictureOutlined style={{ color: "#1677ff" }} />;
  }
  if (name.endsWith(".xlsx") || name.endsWith(".xls") || name.endsWith(".csv")) {
    return <FileExcelOutlined style={{ color: "#389e0d" }} />;
  }
  if (name.endsWith(".txt") || name.endsWith(".json") || name.endsWith(".log")) {
    return <FileTextOutlined style={{ color: "#8c8c8c" }} />;
  }
  return <FileTextOutlined />;
}

interface ArtifactRow {
  key: string;
  category: string;
  name: string;
  fullKey: string;
}

function flattenArtifacts(artifacts: Record<string, unknown> | undefined): ArtifactRow[] {
  const rows: ArtifactRow[] = [];
  if (!artifacts) {
    return rows;
  }
  for (const [category, value] of Object.entries(artifacts)) {
    const keys = Array.isArray(value) ? value : [value];
    for (const item of keys) {
      if (item == null || typeof item !== "string" || !item.trim()) {
        continue;
      }
      const clean = item.startsWith(FAULT_ANALYSIS_KEY_PREFIX)
        ? item
        : `${FAULT_ANALYSIS_KEY_PREFIX}${item}`;
      rows.push({
        key: clean,
        category,
        name: item,
        fullKey: clean,
      });
    }
  }
  return rows;
}

async function downloadArtifact(
  fetchWithAuth: (path: string, init?: RequestInit) => Promise<Response>,
  analysisId: string,
  objectKey: string,
): Promise<void> {
  const encodedKey = objectKey.split("/").map(encodeURIComponent).join("/");
  const response = await fetchWithAuth(`/api/v1/fault-analysis/${analysisId}/artifacts/${encodedKey}`);
  if (!response.ok) {
    const errMsg = await readApiError(response).catch(() => "下载失败");
    throw new Error(errMsg);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  let filename = "";
  if (encodedMatch) {
    filename = decodeURIComponent(encodedMatch[1]);
  } else {
    const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
    filename = plainMatch ? plainMatch[1] : objectKey.split("/").pop() ?? "artifact";
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

interface ArtifactsModalProps {
  analysisId: string | null;
  open: boolean;
  onClose: () => void;
}

/** 产物清单弹窗：以表格呈现 result_json.artifacts，支持逐项下载 */
export function ArtifactsModal({ analysisId, open, onClose }: ArtifactsModalProps) {
  const { message: messageApi } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);

  const canRead = hasPermission("line.read") || hasPermission("line.manage");

  const detailQuery = useQuery({
    queryKey: ["/api/v1/fault-analysis", analysisId],
    enabled: Boolean(user && canRead && open && analysisId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fault-analysis/${analysisId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FaultAnalysisDetail;
    },
  });

  const rows = useMemo(() => {
    if (!detailQuery.data) {
      return [];
    }
    const resultJson = detailQuery.data.result_json as Record<string, unknown> | undefined;
    const artifacts = resultJson?.artifacts as Record<string, unknown> | undefined;
    return flattenArtifacts(artifacts);
  }, [detailQuery.data]);

  const handleDownload = useCallback(async (row: ArtifactRow) => {
    if (!analysisId) return;
    setDownloadingKey(row.fullKey);
    try {
      await downloadArtifact(fetchWithAuth, analysisId, row.fullKey);
      messageApi.success("产物下载成功");
    } catch (error) {
      console.error("下载产物失败", error);
      messageApi.error(error instanceof Error ? error.message : "下载失败，请重试");
    } finally {
      setDownloadingKey(null);
    }
  }, [analysisId, fetchWithAuth, messageApi]);

  const columns = useMemo<ColumnsType<ArtifactRow>>(
    () => [
      {
        title: "分类",
        dataIndex: "category",
        key: "category",
        width: 140,
        render: (value: string) => value || "-",
      },
      {
        title: "文件名",
        dataIndex: "name",
        key: "name",
        ellipsis: true,
        render: (value: string, record: ArtifactRow) => (
          <Space size={6}>
            {artifactIcon(record.name)}
            <Text className="font-mono text-xs">{value}</Text>
          </Space>
        ),
      },
      {
        title: "操作",
        key: "actions",
        width: 90,
        render: (_, record: ArtifactRow) => (
          <Button
            size="small"
            type="link"
            icon={<DownloadOutlined />}
            loading={downloadingKey === record.fullKey}
            onClick={() => void handleDownload(record)}
          >
            下载
          </Button>
        ),
      },
    ],
    [downloadingKey, handleDownload],
  );

  return (
    <Modal
      title="产物清单"
      open={open}
      onCancel={onClose}
      footer={null}
      width={760}
      destroyOnHidden
    >
      {detailQuery.isLoading ? (
        <div className="flex items-center justify-center py-10">
          <Spin />
        </div>
      ) : detailQuery.error ? (
        <Alert
          type="error"
          showIcon
          message="加载失败"
          description={detailQuery.error instanceof Error ? detailQuery.error.message : "未知错误"}
        />
      ) : rows.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该记录暂无产物清单。" />
      ) : (
        <Table<ArtifactRow>
          rowKey="key"
          dataSource={rows}
          columns={columns}
          size="small"
          pagination={false}
          scroll={{ y: 420 }}
        />
      )}
    </Modal>
  );
}
