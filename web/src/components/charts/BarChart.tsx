"use client";

import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Tooltip,
  Legend,
} from "chart.js";
import { Bar } from "react-chartjs-2";
import type { ChartData } from "@/types";

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend);

interface BarChartProps {
  data: ChartData;
  title?: string;
  horizontal?: boolean;
}

export default function BarChart({ data, title, horizontal }: BarChartProps) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      {title && (
        <h3 className="mb-4 text-sm font-medium text-gray-400">{title}</h3>
      )}
      <Bar
        data={{
          labels: data.labels,
          datasets: data.datasets.map((ds) => ({
            ...ds,
            borderWidth: ds.borderWidth ?? 0,
          })),
        }}
        options={{
          indexAxis: horizontal ? "y" : "x",
          responsive: true,
          scales: {
            x: {
              grid: { color: "#374151" },
              ticks: { color: "#9CA3AF" },
            },
            y: {
              grid: { color: "#374151" },
              ticks: { color: "#9CA3AF" },
            },
          },
          plugins: {
            legend: {
              labels: { color: "#9CA3AF" },
            },
          },
        }}
      />
    </div>
  );
}
