"use client";

import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
} from "chart.js";
import { Doughnut } from "react-chartjs-2";
import type { ChartData } from "@/types";

ChartJS.register(ArcElement, Tooltip, Legend);

interface DoughnutChartProps {
  data: ChartData;
  title?: string;
}

export default function DoughnutChart({ data, title }: DoughnutChartProps) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      {title && (
        <h3 className="mb-4 text-sm font-medium text-gray-400">{title}</h3>
      )}
      <Doughnut
        data={{
          labels: data.labels,
          datasets: data.datasets.map((ds) => ({
            ...ds,
            borderWidth: ds.borderWidth ?? 0,
          })),
        }}
        options={{
          responsive: true,
          plugins: {
            legend: {
              position: "bottom",
              labels: { color: "#9CA3AF", padding: 16 },
            },
          },
        }}
      />
    </div>
  );
}
