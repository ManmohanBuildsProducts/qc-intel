"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  fetchBrandMetrics,
  fetchBrandGaps,
  fetchDiscountBattle,
} from "@/lib/api";
import type { BrandMetrics, BrandGaps, DiscountBattle } from "@/types";
import BrandMetricsPanel from "@/components/BrandMetricsPanel";
import DistributionGaps from "@/components/DistributionGaps";
import DiscountBattleComponent from "@/components/DiscountBattle";

export default function BrandDetailPage() {
  const params = useParams();
  const brand = decodeURIComponent(params.brand as string);
  const category = decodeURIComponent(params.category as string);

  const [metrics, setMetrics] = useState<BrandMetrics | null>(null);
  const [gaps, setGaps] = useState<BrandGaps | null>(null);
  const [discountBattle, setDiscountBattle] = useState<DiscountBattle | null>(
    null
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchBrandMetrics(brand, category),
      fetchBrandGaps(brand, category),
      fetchDiscountBattle(brand, category),
    ])
      .then(([metricsRes, gapsRes, discountRes]) => {
        setMetrics(metricsRes.data);
        setGaps(gapsRes.data);
        setDiscountBattle(discountRes.data);
      })
      .finally(() => setLoading(false));
  }, [brand, category]);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-64 rounded bg-gray-900 animate-pulse" />
        <div className="h-32 rounded-xl bg-gray-900 animate-pulse" />
        <div className="h-64 rounded-xl bg-gray-900 animate-pulse" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm text-gray-500">
        <Link
          href="/brand"
          className="hover:text-gray-300 transition-colors"
        >
          Brand HQ
        </Link>
        <span>›</span>
        <Link
          href={`/brand?selected=${encodeURIComponent(brand)}`}
          className="hover:text-gray-300 transition-colors"
        >
          {brand}
        </Link>
        <span>›</span>
        <span className="text-gray-300">{category}</span>
      </nav>

      <h1 className="text-2xl font-bold text-gray-100">
        {brand}{" "}
        <span className="text-gray-500 font-normal">in {category}</span>
      </h1>

      {/* Distribution Gaps */}
      {gaps && <DistributionGaps gaps={gaps} />}

      {/* Discount Battle */}
      {discountBattle && <DiscountBattleComponent data={discountBattle} />}

      {/* Existing Brand Metrics Panel */}
      {metrics && <BrandMetricsPanel brand={brand} metrics={metrics} />}
    </div>
  );
}
