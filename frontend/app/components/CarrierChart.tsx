"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { carrierColor, carrierName } from "../lib/carriers";

type Carrier = {
  carrier: string;
  total_flights: number;
  on_time_rate: number;
  cancellation_rate: number;
};

export default function CarrierChart({ data }: { data: Carrier[] }) {
  const chartData = [...data]
    .sort((a, b) => b.on_time_rate - a.on_time_rate)
    .map((d) => ({
      carrier: d.carrier,
      onTimePct: Math.round(d.on_time_rate * 1000) / 10,
    }));

  return (
    <div style={{ width: "100%", height: 340 }}>
      <ResponsiveContainer>
        <BarChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 24 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2e3542" />
          <XAxis dataKey="carrier" tick={<CarrierTick />} height={40} interval={0} />
          <YAxis
            tick={{ fontSize: 11, fill: "#9099a8" }}
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip content={<CarrierTooltip />} cursor={{ fill: "rgba(232, 163, 61, 0.08)" }} />
          <Bar dataKey="onTimePct" radius={[4, 4, 0, 0]}>
            {chartData.map((d, i) => (
              <Cell key={i} fill={carrierColor(d.carrier)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function CarrierTooltip({ active, payload, label }: any) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div
      style={{
        background: "#1a2029",
        border: "1px solid #2e3542",
        borderRadius: 4,
        padding: "0.6rem 0.85rem",
      }}
    >
      <div style={{ color: "#9099a8", fontSize: "0.8rem", marginBottom: 4 }}>
        {carrierName(label as string)}
      </div>
      <div style={{ color: "#f3efe4", fontSize: "0.95rem" }}>
        On-time rate: {payload[0].value}%
      </div>
    </div>
  );
}

// Renders each x-axis label as a small colored code-badge instead of plain text,
// so the carrier's brand color is visible even below the bar.
function CarrierTick(props: any) {
  const { x, y, payload } = props;
  const code = payload.value as string;
  const color = carrierColor(code);
  return (
    <g transform={`translate(${x},${y})`}>
      <rect x={-14} y={8} width={28} height={16} rx={3} fill={color} opacity={0.9} />
      <text
        x={0}
        y={19}
        textAnchor="middle"
        fontSize={10}
        fontWeight={600}
        fill="#12151c"
        fontFamily="var(--font-mono), monospace"
      >
        {code}
      </text>
    </g>
  );
}
