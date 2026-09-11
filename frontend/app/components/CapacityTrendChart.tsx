"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CapacityTrendPoint } from "../decision-center/types";

function CapacityTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="capacity-chart-tooltip">
      <strong>{label}</strong>
      <span>Seats filled: {payload.find((item: any) => item.dataKey === "loadPct")?.value ?? "—"}%</span>
      <span>On-time: {payload.find((item: any) => item.dataKey === "onTimePct")?.value ?? "—"}%</span>
    </div>
  );
}

export default function CapacityTrendChart({ data }: { data: CapacityTrendPoint[] }) {
  const chartData = data.map((point) => ({
    month: point.month,
    loadPct: point.load_factor == null ? null : Math.round(point.load_factor * 1000) / 10,
    onTimePct: point.on_time_rate == null ? null : Math.round(point.on_time_rate * 1000) / 10,
  }));

  return (
    <div className="capacity-chart-wrap">
      <div className="capacity-chart-legend-note">
        <span><i className="chart-key chart-key-teal" /> Seats filled</span>
        <span><i className="chart-key chart-key-amber" /> On-time</span>
      </div>
      <div className="capacity-chart" aria-label="Monthly seats filled and on-time rate trend">
        <ResponsiveContainer>
          <LineChart data={chartData} margin={{ top: 10, right: 18, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--seam)" />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 10, fill: "var(--flap-dim)" }}
              interval={Math.max(0, Math.floor(chartData.length / 10) - 1)}
              angle={-35}
              textAnchor="end"
              height={48}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: "var(--flap-dim)" }}
              tickFormatter={(value) => `${value}%`}
            />
            <Tooltip content={<CapacityTooltip />} />
            <Legend content={() => null} />
            <Line type="monotone" dataKey="loadPct" name="Seats filled" stroke="#5eead4" strokeWidth={2.4} dot={false} connectNulls />
            <Line type="monotone" dataKey="onTimePct" name="On-time" stroke="#f7c56a" strokeWidth={2.4} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
