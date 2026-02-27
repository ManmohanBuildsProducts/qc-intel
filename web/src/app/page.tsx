"use client";

import { useEffect, useState } from "react";
import StatsCard from "@/components/StatsCard";
import DoughnutChart from "@/components/charts/DoughnutChart";
import BarChart from "@/components/charts/BarChart";
import { CardSkeleton } from "@/components/LoadingSkeleton";
import { fetchDashboardStats, fetchChartData } from "@/lib/api";
import type { DashboardStats, ChartData } from "@/types";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [brandShare, setBrandShare] = useState<ChartData | null>(null);
  const [platformCoverage, setPlatformCoverage] = useState<ChartData | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDashboardStats()
      .then((res) => setStats(res.data))
      .catch(() => setError("Failed to load dashboard stats"));

    fetchChartData("brand-share", { category: "Dairy & Bread" })
      .then((res) => setBrandShare(res.data))
      .catch(() => {});

    fetchChartData("platform-coverage")
      .then((res) => setPlatformCoverage(res.data))
      .catch(() => {});
  }, []);

  return (
    <div>
      <h2 className="mb-6 text-2xl font-bold text-gray-100">Dashboard</h2>

      {error && (
        <div className="mb-6 rounded-lg border border-red-800 bg-red-900/20 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats ? (
          <>
            <StatsCard icon="P" label="Products" value={stats.products} />
            <StatsCard icon="B" label="Brands" value={stats.brands} />
            <StatsCard
              icon="C"
              label="Categories"
              value={stats.categories}
            />
            <StatsCard icon="#" label="Platforms" value={stats.platforms} />
          </>
        ) : (
          <>
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {brandShare ? (
          <DoughnutChart data={brandShare} title="Brand Share — Dairy & Bread" />
        ) : (
          <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
            <div className="h-64 animate-pulse rounded bg-gray-800" />
          </div>
        )}
        {platformCoverage ? (
          <BarChart data={platformCoverage} title="Platform Coverage" />
        ) : (
          <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
            <div className="h-64 animate-pulse rounded bg-gray-800" />
          </div>
        )}
      </div>
    </div>
  );
}
