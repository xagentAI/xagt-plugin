"use client";

import { useState, useEffect } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { IconTimeline } from "@tabler/icons-react";

interface ExposurePoint {
  date: string;
  value: number;
}

interface ExposureData {
  total: string;
  change: string;
  period: string;
  points: ExposurePoint[];
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ value: number; payload: ExposurePoint }>;
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="flex flex-col items-center -translate-y-3 pointer-events-none">
        <div className="px-3 py-1.5 bg-white text-black text-xs font-mono font-bold rounded-lg shadow-xl flex items-center gap-2 border border-neutral-200">
          <span className="text-neutral-500 font-normal">{data.date}</span>
          <span className="font-bold text-black">{data.value.toLocaleString()}</span>
        </div>
      </div>
    );
  }
  return null;
}

export function ExposureTimelineChart({
  initialData,
}: {
  initialData?: ExposureData;
}) {
  const [data, setData] = useState<ExposureData>(
    initialData || {
      total: "0",
      change: "0.0%",
      period: "last 30 days",
      points: [],
    }
  );
  const [mounted, setMounted] = useState(false);

  // Synchronize when initialData arrives from parent API call
  useEffect(() => {
    if (initialData) {
      setData(initialData);
    }
  }, [initialData]);

  // Client-side fetch fallback if parent doesn't provide initialData
  useEffect(() => {
    setMounted(true);
    if (!initialData) {
      fetch("/api/dashboard/exposure")
        .then((res) => (res.ok ? res.json() : null))
        .then((res) => {
          if (res) {
            setData({
              total: res.formattedTotal || res.total?.toLocaleString() || "0",
              change: res.changeFormatted || "0.0%",
              period: res.period || "last 30 days",
              points: res.points || [],
            });
          }
        })
        .catch(() => {});
    }
  }, [initialData]);

  const points = data.points ?? [];
  const hasData = points.length > 0 && points.some((p) => p.value > 0);

  return (
    <div className="rounded-2xl bg-[#181818] p-6 sm:p-8 mb-8 border border-white/[0.04]">
      {/* Header Info */}
      <div className="text-sm font-medium text-neutral-400 font-sans mb-1">
        Exposure Timeline
      </div>
      <div className="flex items-baseline gap-3 mb-6">
        <span className="text-4xl sm:text-5xl font-bold font-mono tracking-tight text-white">
          {data.total}
        </span>
        <span className="text-xs font-mono text-emerald-400 font-medium">
          {data.change} <span className="text-neutral-500">{data.period}</span>
        </span>
      </div>

      {/* Recharts Canvas */}
      <div className="relative w-full h-48 sm:h-64">
        {!mounted ? (
          <div className="w-full h-full animate-pulse bg-white/[0.02] rounded-lg" />
        ) : hasData ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={points}
              margin={{ top: 25, right: 10, left: 10, bottom: 5 }}
            >
              <XAxis dataKey="date" hide />
              <YAxis hide domain={["dataMin - 100", "dataMax + 100"]} />
              <Tooltip
                content={<CustomTooltip />}
                cursor={{
                  stroke: "rgba(255,255,255,0.2)",
                  strokeWidth: 1,
                  strokeDasharray: "3 3",
                }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#ffffff"
                strokeWidth={1.8}
                dot={false}
                activeDot={{
                  r: 5,
                  fill: "#ffffff",
                  stroke: "#181818",
                  strokeWidth: 2,
                }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="w-full h-full rounded-xl border border-dashed border-white/[0.06] bg-white/[0.01] flex flex-col items-center justify-center p-6 text-center">
            <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/[0.05] flex items-center justify-center text-neutral-500 mb-2.5">
              <IconTimeline size={20} />
            </div>
            <p className="text-xs font-medium text-neutral-400 font-sans">
              No exposure activity yet
            </p>
            <p className="text-[11px] text-neutral-500 font-mono mt-1 max-w-xs">
              Portfolio metrics will populate automatically when you launch or trade tokens.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
