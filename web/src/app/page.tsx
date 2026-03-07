"use client";

import { useEffect, useState } from "react";
import StatsCard from "@/components/StatsCard";
import DoughnutChart from "@/components/charts/DoughnutChart";
import BarChart from "@/components/charts/BarChart";
import { CardSkeleton } from "@/components/LoadingSkeleton";
import { fetchDashboardStats, fetchChartData, fetchCategories, fetchBrands } from "@/lib/api";
import type { DashboardStats, ChartData, Category, Brand } from "@/types";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [selectedCategory, setSelectedCategory] = useState("Dairy & Bread");
  const [selectedBrand, setSelectedBrand] = useState("Amul");
  const [brandShare, setBrandShare] = useState<ChartData | null>(null);
  const [platformCoverage, setPlatformCoverage] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load stats + meta once
  useEffect(() => {
    fetchDashboardStats()
      .then((res) => setStats(res.data))
      .catch(() => setError("Failed to load dashboard stats"));

    fetchCategories()
      .then((res) => setCategories(res.data))
      .catch(() => {});

    fetchBrands()
      .then((res) => setBrands(res.data))
      .catch(() => {});
  }, []);

  // Reload brand share when category changes
  useEffect(() => {
    if (!selectedCategory) return;
    setBrandShare(null);
    fetchChartData("brand-share", { category: selectedCategory })
      .then((res) => setBrandShare(res.data))
      .catch(() => setBrandShare(null));
  }, [selectedCategory]);

  // Reload platform coverage when brand changes
  useEffect(() => {
    if (!selectedBrand) return;
    setPlatformCoverage(null);
    fetchChartData("platform-coverage", { brand: selectedBrand })
      .then((res) => setPlatformCoverage(res.data))
      .catch(() => setPlatformCoverage(null));
  }, [selectedBrand]);

  const lastScrape = stats?.last_scrape
    ? new Date(stats.last_scrape).toLocaleString("en-IN", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : null;

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-100">Dashboard</h2>
        {lastScrape && (
          <span className="text-xs text-gray-500">
            Last scraped: {lastScrape}
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-900/20 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats ? (
          <>
            <StatsCard icon="P" label="Products" value={stats.products} />
            <StatsCard icon="B" label="Brands" value={stats.brands} />
            <StatsCard icon="C" label="Categories" value={stats.categories} />
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

      {/* Category coverage breakdown */}
      {categories.length > 0 && (
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Category Coverage
          </h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {categories.map((cat) => (
              <button
                key={cat.name}
                onClick={() => setSelectedCategory(cat.name)}
                className={`rounded-lg border p-3 text-left transition-colors ${
                  selectedCategory === cat.name
                    ? "border-emerald-500/50 bg-emerald-500/10"
                    : "border-gray-700 bg-gray-800/50 hover:border-gray-600"
                }`}
              >
                <div className="truncate text-xs font-medium text-gray-200">
                  {cat.name}
                </div>
                <div className="mt-1 text-lg font-bold text-gray-100">
                  {cat.product_count}
                </div>
                <div className="text-xs text-gray-500">
                  {cat.brand_count} brands
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Brand share — controlled by category selector above */}
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-300">
              Brand Share
            </h3>
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-300 focus:outline-none"
            >
              {categories.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          {brandShare ? (
            <DoughnutChart data={brandShare} title="" />
          ) : (
            <div className="h-64 animate-pulse rounded bg-gray-800" />
          )}
        </div>

        {/* Platform coverage — controlled by brand selector */}
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-300">
              Platform Coverage
            </h3>
            <select
              value={selectedBrand}
              onChange={(e) => setSelectedBrand(e.target.value)}
              className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-300 focus:outline-none"
            >
              {brands.slice(0, 30).map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>
          {platformCoverage ? (
            <BarChart data={platformCoverage} title="" />
          ) : (
            <div className="h-64 animate-pulse rounded bg-gray-800" />
          )}
        </div>
      </div>
    </div>
  );
}
