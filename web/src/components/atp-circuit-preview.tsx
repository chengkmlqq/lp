"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Card, Descriptions, Empty, Spin, Typography } from "antd";
import { Graph } from "@antv/x6";
import { graphlib, layout } from "@dagrejs/dagre";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { AtpTopologyNode, AtpTopologyResponse } from "@/types/auth";

const { Text } = Typography;

/**
 * 节点样式表：按 node_type 区分配色。
 * source⚡ / insulator🔗 / tower_body🗼 / tower_arm— / resistor⏛ / ground⏚ / line〰
 */
const NODE_STYLES: Record<string, { fill: string; stroke: string; icon: string }> = {
  source: { fill: "#e11d48", stroke: "#9f1239", icon: "⚡" },
  insulator: { fill: "#0284c7", stroke: "#075985", icon: "🔗" },
  tower_body: { fill: "#7c3aed", stroke: "#5b21b6", icon: "🗼" },
  tower_arm: { fill: "#0d9488", stroke: "#0f766e", icon: "⌗" },
  resistor: { fill: "#f59e0b", stroke: "#b45309", icon: "⏛" },
  ground: { fill: "#475569", stroke: "#334155", icon: "⏚" },
  line: { fill: "#334155", stroke: "#1e293b", icon: "〰" },
};

const DEFAULT_NODE_STYLE = { fill: "#334155", stroke: "#1e293b", icon: "●" };
const NODE_WIDTH = 190;
const NODE_HEIGHT = 64;
const NODE_RADIUS = 8;

function nodeStyle(nodeType: string): { fill: string; stroke: string; icon: string } {
  return NODE_STYLES[nodeType] ?? DEFAULT_NODE_STYLE;
}

function formatParamValue(value: unknown): string {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/\.?0+$/, "");
  }
  return String(value ?? "-");
}

/**
 * 元件参数详情面板。
 */
export function AtpNodeDetailPanel({ node }: { node: AtpTopologyNode | null }) {
  if (!node) {
    return (
      <Card size="small" title="元件参数">
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="点击电路元件查看参数" />
      </Card>
    );
  }

  const style = nodeStyle(node.node_type);
  const params = node.params as Record<string, unknown>;
  const entries = Object.entries(params).filter(([key]) => key !== "param");

  return (
    <Card
      size="small"
      title={
        <span>
          {style.icon} {node.label}
        </span>
      }
    >
      <Descriptions
        size="small"
        column={1}
        bordered
        items={[
          { key: "type", label: "类型", children: node.node_type },
          ...(typeof params.param === "string"
            ? [{ key: "param", label: "参数", children: params.param as string }]
            : []),
          ...entries.map(([key, value]) => ({
            key,
            label: key,
            children: formatParamValue(value),
          })),
        ]}
      />
    </Card>
  );
}

interface AtpCircuitPreviewProps {
  assetId: string;
  height?: number;
  onSelectNode?: (node: AtpTopologyNode | null) => void;
}

/**
 * ATP 电路拓扑在线预览。
 *
 * 用 @antv/x6 渲染后端解析出的 nodes/edges，@dagrejs/dagre 做 TB 布局。
 * 点击元件 → 通过 onSelectNode 回填右侧详情面板（默认内嵌 AtpNodeDetailPanel）。
 * 右下角浮层显示模型参数（前 6 个 + 总数）。
 */
export default function AtpCircuitPreview({
  assetId,
  height = 520,
  onSelectNode,
}: AtpCircuitPreviewProps) {
  const { user, fetchWithAuth } = useAuth();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [selectedNode, setSelectedNode] = useState<AtpTopologyNode | null>(null);
  const [renderError, setRenderError] = useState("");
  const onSelectNodeRef = useRef(onSelectNode);
  onSelectNodeRef.current = onSelectNode;

  const topologyQuery = useQuery({
    queryKey: ["atp-topology", assetId],
    enabled: Boolean(user && assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/topology`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpTopologyResponse;
    },
  });

  const topology = topologyQuery.data?.topology;
  const parameters = topology?.parameters ?? {};
  const parameterEntries = useMemo(
    () => Object.entries(parameters),
    [parameters],
  );
  const displayedParameters = parameterEntries.slice(0, 6);
  const parameterTotal = parameterEntries.length;

  const renderTopology = useCallback(
    (data: AtpTopologyResponse["topology"]) => {
      const container = containerRef.current;
      if (!container) {
        return;
      }

      // 清理旧图实例，防止内存泄漏
      graphRef.current?.dispose();
      graphRef.current = null;

      const g = new graphlib.Graph();
      g.setGraph({ rankdir: "TB", nodesep: 80, ranksep: 90, marginx: 24, marginy: 24 });
      data.nodes.forEach((node) => {
        g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
      });
      data.edges.forEach((edge) => {
        if (data.nodes.some((n) => n.id === edge.source) && data.nodes.some((n) => n.id === edge.target)) {
          g.setEdge(edge.source, edge.target);
        }
      });
      layout(g);

      const graph = new Graph({
        container,
        autoResize: true,
        background: { color: "#0f172a" },
        grid: { visible: true, size: 20, type: "dot", args: { color: "#1e293b", thickness: 1 } },
        panning: { enabled: true },
        mousewheel: { enabled: true, modifiers: ["ctrl", "meta"], minScale: 0.3, maxScale: 3 },
        connecting: {
          allowBlank: false,
          allowLoop: false,
          allowNode: false,
          allowEdge: false,
          allowPort: false,
          allowMulti: false,
          highlight: false,
          snap: false,
          anchor: "center",
          connectionPoint: "anchor",
          router: "orth",
          connector: "rounded",
          validateConnection: () => false,
        },
        interacting: {
          nodeMovable: true,
          edgeMovable: false,
          edgeLabelMovable: false,
        },
        highlighting: {
          default: {
            name: "stroke",
            args: { padding: 4, attrs: { stroke: "#fbbf24" } },
          },
        },
      });

      // 添加节点
      const nodeById = new Map(data.nodes.map((node) => [node.id, node]));
      data.nodes.forEach((node) => {
        const layoutInfo = g.node(node.id) ?? { x: 0, y: 0, width: NODE_WIDTH, height: NODE_HEIGHT };
        const style = nodeStyle(node.node_type);
        const paramValue =
          typeof node.params?.value === "number"
            ? `${formatParamValue(node.params.value)}${typeof node.params.unit === "string" ? node.params.unit : ""}`
            : "";
        graph.addNode({
          id: node.id,
          x: (layoutInfo.x as number) - NODE_WIDTH / 2,
          y: (layoutInfo.y as number) - NODE_HEIGHT / 2,
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
          shape: "rect",
          attrs: {
            body: {
              fill: style.fill,
              stroke: style.stroke,
              rx: NODE_RADIUS,
              ry: NODE_RADIUS,
              strokeWidth: 1.5,
            },
            label: {
              text: `${style.icon} ${node.label}${paramValue ? `\n${paramValue}` : ""}`,
              fill: "#f8fafc",
              fontSize: 13,
              fontWeight: 600,
              textAnchor: "middle",
              textVerticalAnchor: "middle",
              textWrap: { width: NODE_WIDTH - 16, height: NODE_HEIGHT - 12 },
              lineHeight: 18,
            },
          },
          data: { nodeType: node.node_type },
        });
      });

      // 添加边
      data.edges.forEach((edge) => {
        if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) {
          return;
        }
        graph.addEdge({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          shape: "edge",
          attrs: {
            line: {
              stroke: "#94a3b8",
              strokeWidth: 1.5,
              targetMarker: {
                name: "block",
                width: 8,
                height: 6,
                style: { fill: "#94a3b8" },
              },
            },
          },
          labels: edge.label
            ? [
                {
                  attrs: { label: { text: edge.label, fill: "#cbd5e1", fontSize: 11 } },
                  position: 0.5,
                },
              ]
            : [],
        });
      });

      // 点击节点 → 选中详情
      graph.on("node:click", ({ node }) => {
        const sourceNode = nodeById.get(node.id);
        if (sourceNode) {
          setSelectedNode(sourceNode);
          onSelectNodeRef.current?.(sourceNode);
        }
      });
      graph.on("blank:click", () => {
        setSelectedNode(null);
        onSelectNodeRef.current?.(null);
      });

      graph.centerContent();
      graph.zoomToFit({ padding: 32, maxScale: 1 });
      graphRef.current = graph;
      setRenderError("");
    },
    [],
  );

  useEffect(() => {
    if (!topology) {
      return;
    }
    try {
      renderTopology(topology);
    } catch (error) {
      setRenderError(error instanceof Error ? error.message : "电路图渲染失败");
    }
    return () => {
      graphRef.current?.dispose();
      graphRef.current = null;
    };
  }, [topology, renderTopology]);

  const isLoading = topologyQuery.isLoading;
  const isError = topologyQuery.isError;
  const errorMessage = topologyQuery.error instanceof Error ? topologyQuery.error.message : "";
  const hasNodes = Boolean(topology && topology.nodes.length > 0);
  const nodeCount = topology?.nodes.length ?? 0;
  const edgeCount = topology?.edges.length ?? 0;

  return (
    <Card
      size="small"
      title="电路拓扑预览"
      styles={{ body: { padding: 0 } }}
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          {hasNodes ? `${nodeCount} 个元件 · ${edgeCount} 条连接` : ""}
        </Text>
      }
    >
      <div style={{ position: "relative", width: "100%", height }}>
        <div
          ref={containerRef}
          style={{
            width: "100%",
            height: "100%",
            borderRadius: 8,
            overflow: "hidden",
            backgroundColor: "#0f172a",
          }}
        />

        {isLoading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(15,23,42,0.4)", zIndex: 10 }}>
            <Spin />
          </div>
        )}

        {isError && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "#0f172a", zIndex: 10 }}>
            <Alert type="error" message="电路拓扑加载失败" description={errorMessage} style={{ maxWidth: 360 }} />
          </div>
        )}

        {renderError && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "#0f172a", zIndex: 10 }}>
            <Alert type="error" message="电路图渲染失败" description={renderError} style={{ maxWidth: 360 }} />
          </div>
        )}

        {!isLoading && !isError && !renderError && !hasNodes && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "#0f172a", zIndex: 10 }}>
            <Empty description="暂无电路拓扑数据" />
          </div>
        )}

        {/* 右下角参数浮层 */}
        {hasNodes && parameterTotal > 0 && (
          <div
            style={{
              position: "absolute",
              right: 12,
              bottom: 12,
              zIndex: 5,
              backgroundColor: "rgba(15,23,42,0.85)",
              border: "1px solid #334155",
              borderRadius: 8,
              padding: "8px 12px",
              maxWidth: 240,
            }}
          >
            <Text style={{ color: "#cbd5e1", fontSize: 12, fontWeight: 600 }}>模型参数</Text>
            <div style={{ marginTop: 4 }}>
              {displayedParameters.map(([key, value]) => (
                <div key={key} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <Text style={{ color: "#94a3b8", fontSize: 12 }}>{key}</Text>
                  <Text style={{ color: "#e2e8f0", fontSize: 12 }}>{formatParamValue(value)}</Text>
                </div>
              ))}
            </div>
            {parameterTotal > 6 && (
              <Text style={{ color: "#64748b", fontSize: 11 }}>… 共 {parameterTotal} 个参数</Text>
            )}
          </div>
        )}
      </div>

      <div style={{ padding: 12 }}>
        <AtpNodeDetailPanel node={selectedNode} />
      </div>
    </Card>
  );
}
