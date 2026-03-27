"use client";

import {
  Chart as ChartJS,
  LinearScale,
  PointElement,
  Tooltip,
  Legend,
} from "chart.js";
import { Bubble } from "react-chartjs-2";
import type { LandscapeBrand } from "@/types";

ChartJS.register(LinearScale, PointElement, Tooltip, Legend);

const PLATFORM_COLORS: Record<number, string> = {
  1: "#6B7280", // gray
  2: "#3B82F6", // blue
  3: "#10b981", // emerald
};

interface Props {
  brands: LandscapeBrand[];
  title?: string;
}

export default function BubbleChart({ brands, title }: Props) {
  const data = {
    datasets: [
      {
        label: "Brands",
        data: brands.map((b) => ({
          x: b.avg_price,
          y: b.avg_discount_pct,
          r: Math.max(Math.sqrt(b.sku_count) * 5, 4),
        })),
        backgroundColor: brands.map(
          (b) => (PLATFORM_COLORS[b.platform_count] || PLATFORM_COLORS[1]) + "80"
        ),
        borderColor: brands.map(
          (b) => PLATFORM_COLORS[b.platform_count] || PLATFORM_COLORS[1]
        ),
        borderWidth: 1,
      },
    ],
  };

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
      {title && (
        <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-4">
          {title}
        </h4>
      )}
      <Bubble
        data={data}
        options={{
          responsive: true,
          scales: {
            x: {
              grid: { color: "#374151" },
              ticks: { color: "#9CA3AF" },
              title: {
                display: true,
                text: "Avg Price (₹)",
                color: "#9CA3AF",
              },
            },
            y: {
              grid: { color: "#374151" },
              ticks: { color: "#9CA3AF" },
              title: {
                display: true,
                text: "Avg Discount %",
                color: "#9CA3AF",
              },
              beginAtZero: true,
            },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (_ctx) => {
                  const idx = _ctx.dataIndex;
                  const b = brands[idx];
                  return [
                    b.brand,
                    `Price: ₹${b.avg_price}`,
                    `Discount: ${b.avg_discount_pct}%`,
                    `SKUs: ${b.sku_count}`,
                    `Platforms: ${b.platforms.join(", ")}`,
                  ];
                },
              },
            },
          },
        }}
      />
      <div className="mt-3 flex gap-4 justify-center text-[10px] text-gray-500">
        <span>
          <span className="inline-block w-2 h-2 rounded-full bg-gray-500 mr-1" />
          1 platform
        </span>
        <span>
          <span className="inline-block w-2 h-2 rounded-full bg-blue-500 mr-1" />
          2 platforms
        </span>
        <span>
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 mr-1" />
          3 platforms
        </span>
      </div>
    </div>
  );
}
