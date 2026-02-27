"use client";

import { useState } from "react";
import BrandCategorySelector from "@/components/BrandCategorySelector";
import ReportViewer from "@/components/ReportViewer";
import { ReportSkeleton } from "@/components/LoadingSkeleton";
import { generateReport } from "@/lib/api";
import type { ReportResponse } from "@/types";

export default function ReportsPage() {
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate(brand: string, category: string) {
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const res = await generateReport(brand, category);
      setReport(res.data);
    } catch {
      setError("Failed to generate report. Is the API running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-gray-100">Reports</h2>
        <p className="text-sm text-gray-400">
          Generate AI-powered market intelligence reports
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
            Generating report with Claude Opus... this may take 10-30 seconds.
          </p>
          <ReportSkeleton />
        </div>
      )}

      {report && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="rounded-md bg-emerald-500/20 px-2 py-1 text-xs font-medium text-emerald-400">
              {report.brand}
            </span>
            <span className="rounded-md bg-gray-800 px-2 py-1 text-xs text-gray-400">
              {report.category}
            </span>
            <span className="text-xs text-gray-500">
              {report.product_count} products across {report.platform_count}{" "}
              platforms
            </span>
          </div>
          <ReportViewer content={report.content} />
        </div>
      )}
    </div>
  );
}
