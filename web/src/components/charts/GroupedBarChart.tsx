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

interface Props {
  data: ChartData;
  title?: string;
}

export default function GroupedBarChart({ data, title }: Props) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
      {title && (
        <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-4">
          {title}
        </h4>
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
          responsive: true,
          scales: {
            x: {
              grid: { color: "#374151" },
              ticks: { color: "#9CA3AF", font: { size: 10 } },
            },
            y: {
              grid: { color: "#374151" },
              ticks: { color: "#9CA3AF" },
              beginAtZero: true,
            },
          },
          plugins: {
            legend: {
              labels: { color: "#9CA3AF", boxWidth: 12 },
            },
          },
        }}
      />
    </div>
  );
}
