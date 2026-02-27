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

interface PriceDistributionChartProps {
  data: ChartData;
}

export default function PriceDistributionChart({
  data,
}: PriceDistributionChartProps) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <h3 className="mb-4 text-sm font-medium text-gray-400">
        Price Distribution
      </h3>
      <Bar
        data={{
          labels: data.labels,
          datasets: data.datasets.map((ds) => ({
            ...ds,
            borderWidth: ds.borderWidth ?? 0,
            backgroundColor: ds.backgroundColor || "#10B981",
          })),
        }}
        options={{
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
            legend: { display: false },
          },
        }}
      />
    </div>
  );
}
