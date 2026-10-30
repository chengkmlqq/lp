"use client";

// ATP 测试波形视图:解析后端返回的 pl4 波形数据(通道/时间/采样),
// 用纯 SVG 绘制多通道折线图,支持通道多选/全选。无第三方绘图依赖。
import { useMemo, useState } from "react";

export interface WaveformChannel {
  name: string;
  unit: string;
}

export interface WaveformData {
  run_id: string;
  channels: WaveformChannel[];
  time: number[];
  values: number[][];
  sample_count: number;
  downsampled_count: number;
  file_size: number;
}

const CHANNEL_COLORS = [
  "#1668dc", "#d4380d", "#389e0d", "#531dab", "#c41d7f",
  "#08979c", "#8c8c8c", "#fa8c16", "#7cb305", "#eb2f96",
];

interface WaveformChartProps {
  data: WaveformData;
}

export function WaveformChart({ data }: WaveformChartProps) {
  const [selected, setSelected] = useState<Set<number>>(() => {
    // 默认选前 3 个通道(通常是三相电压/电流),避免一上来 34 条线糊成一团
    const initial = new Set<number>();
    for (let i = 0; i < Math.min(3, data.channels.length); i += 1) initial.add(i);
    return initial;
  });

  const W = 860;
  const H = 320;
  const PAD = { top: 16, right: 16, bottom: 28, left: 56 };

  const { times, series, yMin, yMax, channelMeta } = useMemo(() => {
    const times = data.time ?? [];
    const series: Array<{ index: number; name: string; unit: string; points: string; color: string }> = [];
    let yMin = Infinity;
    let yMax = -Infinity;
    const selectedArr = [...selected].sort((a, b) => a - b);
    for (const ci of selectedArr) {
      const vals = data.values?.[ci] ?? [];
      if (vals.length === 0) continue;
      for (const v of vals) {
        if (Number.isFinite(v)) {
          if (v < yMin) yMin = v;
          if (v > yMax) yMax = v;
        }
      }
    }
    if (!Number.isFinite(yMin)) yMin = 0;
    if (!Number.isFinite(yMax)) yMax = 1;
    if (yMax === yMin) {
      yMax += 1;
      yMin -= 1;
    }
    const pad = (yMax - yMin) * 0.08;
    yMin -= pad;
    yMax += pad;

    const tMin = times[0] ?? 0;
    const tMax = times[times.length - 1] ?? 1;
    const xScale = (t: number) => PAD.left + ((t - tMin) / (tMax - tMin || 1)) * (W - PAD.left - PAD.right);
    const yScale = (v: number) => H - PAD.bottom - ((v - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom);

    for (const ci of selectedArr) {
      const vals = data.values?.[ci] ?? [];
      if (vals.length === 0) continue;
      const pts: string[] = [];
      for (let i = 0; i < times.length; i += 1) {
        const v = vals[i];
        if (!Number.isFinite(v)) continue;
        pts.push(`${xScale(times[i]).toFixed(1)},${yScale(v).toFixed(1)}`);
      }
      const ch = data.channels?.[ci];
      series.push({
        index: ci,
        name: ch?.name ?? `CH${ci + 1}`,
        unit: ch?.unit ?? "",
        points: pts.join(" "),
        color: CHANNEL_COLORS[ci % CHANNEL_COLORS.length],
      });
    }
    const channelMeta = (data.channels ?? []).map((ch, i) => ({
      index: i,
      name: ch.name ?? `CH${i + 1}`,
      unit: ch.unit ?? "",
    }));
    return { times, series, yMin, yMax, channelMeta };
  }, [data, selected]);

  const toggleChannel = (index: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const selectAll = () => {
    const all = new Set<number>();
    for (let i = 0; i < (data.channels?.length ?? 0); i += 1) all.add(i);
    setSelected(all);
  };

  const selectNone = () => setSelected(new Set());

  return (
    <div>
      <div style={{ marginBottom: 8, display: "flex", flexWrap: "wrap", gap: "4px 14px", maxHeight: 96, overflow: "auto" }}>
        {channelMeta.map((ch) => (
          <label
            key={ch.index}
            style={{
              fontSize: 12,
              cursor: "pointer",
              color: selected.has(ch.index) ? CHANNEL_COLORS[ch.index % CHANNEL_COLORS.length] : "#999",
              fontWeight: selected.has(ch.index) ? 600 : 400,
              userSelect: "none",
            }}
          >
            <input
              type="checkbox"
              style={{ marginRight: 3 }}
              checked={selected.has(ch.index)}
              onChange={() => toggleChannel(ch.index)}
            />
            {ch.name}
            {ch.unit ? ` [${ch.unit}]` : ""}
          </label>
        ))}
      </div>
      <div style={{ marginBottom: 8, display: "flex", gap: 12 }}>
        <a
          style={{ fontSize: 12 }}
          onClick={(e) => {
            e.preventDefault();
            selectAll();
          }}
          href="#"
        >
          全选
        </a>
        <a
          style={{ fontSize: 12 }}
          onClick={(e) => {
            e.preventDefault();
            selectNone();
          }}
          href="#"
        >
          清空
        </a>
        <span style={{ fontSize: 12, color: "#999" }}>
          采样 {data.sample_count} 点(展示 {data.downsampled_count})
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "auto", background: "#fff", border: "1px solid #eee", borderRadius: 4 }}
      >
        {/* 水平网格线 */}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const y = PAD.top + f * (H - PAD.top - PAD.bottom);
          const val = yMax - f * (yMax - yMin);
          return (
            <g key={f}>
              <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} stroke="#eff4f9" strokeWidth={1} />
              <text x={PAD.left - 6} y={y + 3} textAnchor="end" fontSize={10} fill="#79879c">
                {val.toExponential(2)}
              </text>
            </g>
          );
        })}
        {/* 时间轴刻度 */}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const x = PAD.left + f * (W - PAD.left - PAD.right);
          const t = (times[0] ?? 0) + f * ((times[times.length - 1] ?? 0) - (times[0] ?? 0));
          return (
            <g key={f}>
              <line x1={x} y1={PAD.top} x2={x} y2={H - PAD.bottom} stroke="#f5f7fa" strokeWidth={1} />
              <text x={x} y={H - 8} textAnchor="middle" fontSize={10} fill="#79879c">
                {t.toExponential(2)}
              </text>
            </g>
          );
        })}
        <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={11} fill="#4e5969">
          时间(s)
        </text>
        {series.map((s) => (
          <polyline
            key={s.index}
            points={s.points}
            fill="none"
            stroke={s.color}
            strokeWidth={1.2}
          />
        ))}
      </svg>
      <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: "2px 14px" }}>
        {series.map((s) => (
          <span key={s.index} style={{ fontSize: 12, color: s.color }}>
            {s.name}
            {s.unit ? ` [${s.unit}]` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}