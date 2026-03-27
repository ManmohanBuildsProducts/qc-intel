"use client";

import { useState } from "react";
import Link from "next/link";
import BrandCategorySelector from "@/components/BrandCategorySelector";
import BrandMetricsPanel from "@/components/BrandMetricsPanel";
import ReportViewer from "@/components/ReportViewer";
import { ReportSkeleton } from "@/components/LoadingSkeleton";
import { generateReport, fetchBrandMetrics } from "@/lib/api";
import type { ReportResponse, BrandMetrics } from "@/types";

function extractSection(content: string, heading: string): string {
  const lines = content.split("\n");
  const startIdx = lines.findIndex((l) =>
    l.toLowerCase().includes(heading.toLowerCase())
  );
  if (startIdx === -1) return "";
  const sectionLines: string[] = [];
  for (let i = startIdx + 1; i < lines.length; i++) {
    if (lines[i].startsWith("## ")) break;
    sectionLines.push(lines[i]);
  }
  return sectionLines.join("\n").trim();
}

function KeyInsightsPanel({ report }: { report: ReportResponse }) {
  const whiteSpace = extractSection(report.content, "White Space Analysis");
  const recommendations = extractSection(report.content, "Recommendations");

  if (!whiteSpace && !recommendations) return null;

  return (
    <div className="rounded-xl border border-amber-800/50 bg-amber-950/20 p-6 space-y-5">
      <div className="flex items-center gap-2">
        <span className="text-amber-400 text-lg">◆</span>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-amber-400">
          {report.is_opportunity_mode ? "Opportunity Analysis" : "Key Insights"}
        </h3>
      </div>

      {whiteSpace && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-300/70">
            White Space Analysis
          </h4>
          <div className="prose prose-sm prose-invert max-w-none text-gray-300 prose-li:my-0.5 prose-p:my-1">
            <ReportViewer content={whiteSpace} compact />
          </div>
        </div>
      )}

      {recommendations && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-300/70">
            Recommendations
          </h4>
          <div className="prose prose-sm prose-invert max-w-none text-gray-300 prose-li:my-0.5 prose-p:my-1">
            <ReportViewer content={recommendations} compact />
          </div>
        </div>
      )}
    </div>
  );
}

export default function ReportsPage() {
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [metrics, setMetrics] = useState<BrandMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate(brand: string, category: string) {
    setLoading(true);
    setError(null);
    setReport(null);
    setMetrics(null);
    try {
      const [reportRes, metricsRes] = await Promise.all([
        generateReport(brand, category),
        fetchBrandMetrics(brand, category).catch(() => null),
      ]);
      setReport(reportRes.data);
      if (metricsRes) setMetrics(metricsRes.data);
    } catch {
      setError("Failed to generate report. Is the API running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-gray-100">AI Reports</h2>
        <p className="text-sm text-gray-400">
          Generate Gemini-powered deep dives — competitive analysis, white spaces, and strategic recommendations
        </p>
        <p className="text-xs text-gray-600 mt-1">
          For interactive dashboards, use{" "}
          <a href="/brand" className="text-emerald-500 hover:text-emerald-400">
            Brand HQ
          </a>
        </p>
      </div>

      <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
        <BrandCategorySelector onSelect={handleGenerate} />
      </div>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-900/20 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {loading && (
        <div>
          <p className="mb-4 text-sm text-gray-400">
            Analyzing market with Gemini... this may take 10–30 seconds.
          </p>
          <ReportSkeleton />
        </div>
      )}

      {report && (
        <div className="space-y-6">
          {/* Report header */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-md bg-emerald-500/20 px-2 py-1 text-xs font-medium text-emerald-400">
              {report.brand}
            </span>
            <span className="rounded-md bg-gray-800 px-2 py-1 text-xs text-gray-400">
              {report.category}
            </span>
            {report.is_opportunity_mode ? (
              <span className="rounded-md bg-amber-500/20 px-2 py-1 text-xs font-medium text-amber-400">
                Market Entry Analysis
              </span>
            ) : (
              <span className="text-xs text-gray-500">
                {report.product_count} products across {report.platform_count} platforms
              </span>
            )}
            <Link
              href={`/brand/${encodeURIComponent(report.brand)}/${encodeURIComponent(report.category)}`}
              className="rounded-md border border-emerald-500/20 bg-emerald-500/5 px-2 py-1 text-xs text-emerald-500 hover:bg-emerald-500/10 transition-colors"
            >
              Interactive dashboard &rarr;
            </Link>
          </div>

          {/* Brand metrics panel */}
          {metrics && (
            <div>
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
                Competitive Metrics
              </h3>
              <BrandMetricsPanel brand={report.brand} metrics={metrics} />
            </div>
          )}

          {/* Key insights panel (white space + recommendations) */}
          <KeyInsightsPanel report={report} />

          {/* Full report */}
          <div>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
              Full Report
            </h3>
            <ReportViewer content={report.content} />
          </div>
        </div>
      )}
    </div>
  );
}
