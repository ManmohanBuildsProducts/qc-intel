"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
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
        <div>
          <h2 className="text-2xl font-bold text-gray-100">Market Pulse</h2>
          <p className="text-sm text-gray-500 mt-1">
            Quick commerce landscape across Blinkit, Zepto & Instamart
          </p>
        </div>
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

      {/* Brand HQ CTA */}
      <Link
        href="/brand"
        className="block rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-5 transition-colors hover:border-emerald-500/40 hover:bg-emerald-500/10"
      >
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-emerald-400">
              Start with your brand
            </h3>
            <p className="text-xs text-gray-500 mt-1">
              Get your full competitive scorecard — distribution gaps, discount positioning, and category rank
            </p>
          </div>
          <span className="text-emerald-500 text-lg shrink-0 ml-4">&rarr;</span>
        </div>
      </Link>

      {/* Stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats ? (
          <>
            <StatsCard icon="P" label="Products Tracked" value={stats.products} />
            <StatsCard icon="B" label="Brands Monitored" value={stats.brands} />
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
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
              Category Coverage
            </h3>
            <Link
              href="/category"
              className="text-xs text-emerald-500 hover:text-emerald-400 transition-colors"
            >
              Deep analysis &rarr;
            </Link>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {categories.map((cat) => (
              <Link
                key={cat.name}
                href={`/category?selected=${encodeURIComponent(cat.name)}`}
                onClick={(e) => {
                  e.preventDefault();
                  setSelectedCategory(cat.name);
                }}
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
              </Link>
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
            <div className="flex items-center gap-2">
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
              <Link
                href={`/brand?selected=${encodeURIComponent(selectedBrand)}`}
                className="text-[10px] text-emerald-500 hover:text-emerald-400 whitespace-nowrap"
              >
                Full scorecard &rarr;
              </Link>
            </div>
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
