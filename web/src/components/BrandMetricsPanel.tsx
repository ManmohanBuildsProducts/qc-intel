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
import type { BrandMetrics, PriceParityRow, CompetitorRow } from "@/types";

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend);

const CHART_OPTIONS = {
  responsive: true,
  scales: {
    x: { grid: { color: "#374151" }, ticks: { color: "#9CA3AF", font: { size: 10 } } },
    y: { grid: { color: "#374151" }, ticks: { color: "#9CA3AF" }, beginAtZero: true },
  },
  plugins: { legend: { labels: { color: "#9CA3AF", boxWidth: 12 } } },
} as const;

function StatPill({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: string | number;
  sub?: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        highlight
          ? "border-emerald-500/40 bg-emerald-500/10"
          : "border-gray-700 bg-gray-800/60"
      }`}
    >
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${highlight ? "text-emerald-400" : "text-gray-100"}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function SectionHeader({ title }: { title: string }) {
  return (
    <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
      {title}
    </h4>
  );
}

function PriceHistogramChart({ data }: { data: BrandMetrics["price_histogram"] }) {
  return (
    <Bar
      data={{
        labels: data.labels,
        datasets: [
          { label: "Brand", data: data.brand, backgroundColor: "#10b981", borderWidth: 0 },
          { label: "Category", data: data.category, backgroundColor: "#374151", borderWidth: 0 },
        ],
      }}
      options={{ ...CHART_OPTIONS, plugins: { ...CHART_OPTIONS.plugins, legend: { ...CHART_OPTIONS.plugins.legend } } }}
    />
  );
}

function MrpTiersChart({ data }: { data: BrandMetrics["mrp_tiers"] }) {
  return (
    <Bar
      data={{
        labels: data.labels,
        datasets: [
          { label: "Brand", data: data.brand, backgroundColor: "#10b981", borderWidth: 0 },
          { label: "Category", data: data.category, backgroundColor: "#374151", borderWidth: 0 },
        ],
      }}
      options={CHART_OPTIONS}
    />
  );
}

function ParityTable({ rows }: { rows: PriceParityRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-xs text-gray-500 italic">
        No cross-platform price differences found.
      </p>
    );
  }
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-gray-700 text-gray-500">
          <th className="pb-2 text-left font-medium">Product</th>
          <th className="pb-2 text-right font-medium">Blinkit</th>
          <th className="pb-2 text-right font-medium">Zepto</th>
          <th className="pb-2 text-right font-medium">Delta</th>
          <th className="pb-2 text-right font-medium">Δ%</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.canonical_name} className="border-b border-gray-800">
            <td className="py-2 text-gray-300">{r.canonical_name}</td>
            <td className="py-2 text-right text-gray-300">₹{r.blinkit_price}</td>
            <td className="py-2 text-right text-gray-300">₹{r.zepto_price}</td>
            <td
              className={`py-2 text-right font-medium ${
                r.delta > 0 ? "text-amber-400" : "text-emerald-400"
              }`}
            >
              {r.delta > 0 ? "+" : ""}
              {r.delta}
            </td>
            <td className="py-2 text-right text-gray-500">{r.delta_pct}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CompetitorTable({ rows }: { rows: CompetitorRow[] }) {
  const max = Math.max(...rows.map((r) => r.sku_count), 1);
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.brand} className="flex items-center gap-3">
          <div className={`w-28 shrink-0 text-xs truncate ${r.is_target ? "text-emerald-400 font-semibold" : "text-gray-300"}`}>
            {r.brand}
          </div>
          <div className="flex-1 h-2 rounded-full bg-gray-800 overflow-hidden">
            <div
              className={`h-full rounded-full ${r.is_target ? "bg-emerald-500" : "bg-gray-600"}`}
              style={{ width: `${(r.sku_count / max) * 100}%` }}
            />
          </div>
          <div className="w-6 text-right text-xs text-gray-500 shrink-0">{r.sku_count}</div>
        </div>
      ))}
    </div>
  );
}

interface Props {
  brand: string;
  metrics: BrandMetrics;
}

export default function BrandMetricsPanel({ brand, metrics }: Props) {
  const { share, price_histogram, mrp_tiers, discount, platform_coverage, price_parity, all_competitors, canonical_competitors } = metrics;

  const platformEntries = Object.entries(platform_coverage.by_platform);

  return (
    <div className="space-y-6">
      {/* ── KPI pills ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatPill
          label="Category Rank"
          value={`#${share.rank}`}
          sub={`of ${new Set(all_competitors.map((c) => c.brand)).size} brands`}
          highlight
        />
        <StatPill
          label="SKU Share"
          value={`${share.share_pct}%`}
          sub={`${share.sku_count} of ${share.category_total} SKUs`}
        />
        <StatPill
          label="Avg Discount"
          value={`${discount.brand_avg}%`}
          sub={`Category avg ${discount.category_avg}%`}
        />
        <StatPill
          label="Cross-Platform"
          value={platform_coverage.cross_platform_count}
          sub={`products matched`}
        />
      </div>

      {/* ── Platform coverage ── */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <SectionHeader title="Platform Coverage" />
        <div className="flex flex-wrap gap-4">
          {platformEntries.map(([platform, count]) => (
            <div key={platform} className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500 inline-block" />
              <span className="text-sm text-gray-300 capitalize">{platform}</span>
              <span className="text-sm font-bold text-gray-100">{count}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Charts row ── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
          <SectionHeader title="Price Distribution (vs Category)" />
          <PriceHistogramChart data={price_histogram} />
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
          <SectionHeader title={`MRP Tiers · Budget ≤₹${mrp_tiers.budget_threshold} · Premium >₹${mrp_tiers.premium_threshold}`} />
          <MrpTiersChart data={mrp_tiers} />
        </div>
      </div>

      {/* ── Competitors + parity row ── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
          <SectionHeader title="Brand Competitors (by SKU count)" />
          <CompetitorTable rows={all_competitors} />
          {canonical_competitors.length > 0 && (
            <div className="mt-4 pt-4 border-t border-gray-800">
              <div className="text-xs text-gray-500 mb-2">Direct canonical competitors</div>
              <div className="flex flex-wrap gap-2">
                {canonical_competitors.map((c) => (
                  <span
                    key={c.brand}
                    className="rounded-md bg-purple-500/10 px-2 py-0.5 text-xs text-purple-400 border border-purple-500/20"
                  >
                    {c.brand}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
          <SectionHeader title={`Cross-Platform Price Parity — ${brand}`} />
          <ParityTable rows={price_parity} />
        </div>
      </div>
    </div>
  );
}
