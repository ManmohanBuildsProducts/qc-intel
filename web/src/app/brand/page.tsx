"use client";

import { useState, useEffect } from "react";
import { fetchBrands, fetchBrandScorecard } from "@/lib/api";
import type { Brand, BrandScorecard } from "@/types";
import BrandScorecardHeader from "@/components/BrandScorecard";
import PlatformHeatmap from "@/components/PlatformHeatmap";
import CategoryCard from "@/components/CategoryCard";

export default function BrandHQPage() {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [selectedBrand, setSelectedBrand] = useState("");
  const [scorecard, setScorecard] = useState<BrandScorecard | null>(null);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    fetchBrands().then((res) => setBrands(res.data));
  }, []);

  useEffect(() => {
    if (!selectedBrand) {
      setScorecard(null);
      return;
    }
    setLoading(true);
    fetchBrandScorecard(selectedBrand)
      .then((res) => setScorecard(res.data))
      .finally(() => setLoading(false));
  }, [selectedBrand]);

  const filteredBrands = searchQuery
    ? brands.filter((b) =>
        b.name.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : brands;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">Brand HQ</h1>
        <p className="text-sm text-gray-500 mt-1">
          Select a brand to see its full competitive scorecard
        </p>
      </div>

      {/* Brand Selector */}
      <div className="relative max-w-md">
        <input
          type="text"
          placeholder="Search brands..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg border border-gray-700 bg-gray-800 px-4 py-2.5 text-sm text-gray-200 placeholder-gray-500 focus:border-emerald-500 focus:outline-none"
        />
        {searchQuery && filteredBrands.length > 0 && !selectedBrand && (
          <div className="absolute z-10 mt-1 w-full rounded-lg border border-gray-700 bg-gray-800 shadow-lg max-h-60 overflow-y-auto">
            {filteredBrands.slice(0, 20).map((b) => (
              <button
                key={b.name}
                onClick={() => {
                  setSelectedBrand(b.name);
                  setSearchQuery(b.name);
                }}
                className="w-full px-4 py-2 text-left text-sm text-gray-300 hover:bg-gray-700 hover:text-gray-100 flex justify-between"
              >
                <span>{b.name}</span>
                <span className="text-gray-600">{b.product_count} SKUs</span>
              </button>
            ))}
          </div>
        )}
        {selectedBrand && (
          <button
            onClick={() => {
              setSelectedBrand("");
              setSearchQuery("");
            }}
            className="absolute right-3 top-2.5 text-gray-500 hover:text-gray-300 text-sm"
          >
            ✕
          </button>
        )}
      </div>

      {/* Quick select: top brands */}
      {!selectedBrand && (
        <div className="flex flex-wrap gap-2">
          {brands
            .sort((a, b) => b.product_count - a.product_count)
            .slice(0, 12)
            .map((b) => (
              <button
                key={b.name}
                onClick={() => {
                  setSelectedBrand(b.name);
                  setSearchQuery(b.name);
                }}
                className="rounded-lg border border-gray-700 bg-gray-800/60 px-3 py-1.5 text-xs text-gray-400 hover:border-gray-600 hover:text-gray-200 transition-colors"
              >
                {b.name}{" "}
                <span className="text-gray-600">({b.product_count})</span>
              </button>
            ))}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="space-y-4">
          <div className="h-32 rounded-xl bg-gray-900 animate-pulse" />
          <div className="h-48 rounded-xl bg-gray-900 animate-pulse" />
        </div>
      )}

      {/* Scorecard content */}
      {scorecard && !loading && (
        <>
          <BrandScorecardHeader scorecard={scorecard} />
          <PlatformHeatmap categories={scorecard.categories} />

          {/* Discount Position */}
          <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-4">
              Discount Position by Category
            </h4>
            <div className="space-y-3">
              {scorecard.categories.map((cat) => {
                const diff =
                  cat.avg_discount_pct - cat.category_avg_discount_pct;
                const isUnderPressure = diff > 0;
                return (
                  <div key={cat.category} className="flex items-center gap-3">
                    <div className="w-36 shrink-0 text-xs text-gray-300 truncate">
                      {cat.category}
                    </div>
                    <div className="flex-1 flex items-center gap-2">
                      <div className="flex-1 h-2 rounded-full bg-gray-800 overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            isUnderPressure ? "bg-amber-500" : "bg-emerald-500"
                          }`}
                          style={{
                            width: `${Math.min(cat.avg_discount_pct * 5, 100)}%`,
                          }}
                        />
                      </div>
                      <span className="text-xs text-gray-400 w-12 text-right shrink-0">
                        {cat.avg_discount_pct}%
                      </span>
                    </div>
                    <span
                      className={`text-[10px] w-20 text-right shrink-0 ${
                        isUnderPressure ? "text-amber-400" : "text-emerald-400"
                      }`}
                    >
                      {isUnderPressure ? "+" : ""}
                      {diff.toFixed(1)}% vs cat
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Category Cards */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-4">
              Category Performance
            </h4>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {scorecard.categories.map((cat) => (
                <CategoryCard
                  key={cat.category}
                  brand={scorecard.brand}
                  category={cat}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
