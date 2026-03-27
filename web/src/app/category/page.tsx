"use client";

import { useState, useEffect } from "react";
import {
  fetchCategories,
  fetchCategoryLandscape,
  fetchCategoryWhitespace,
} from "@/lib/api";
import type {
  Category,
  CategoryLandscape,
  CategoryWhitespace,
} from "@/types";
import BubbleChart from "@/components/charts/BubbleChart";
import WhitespaceAnalysis from "@/components/WhitespaceAnalysis";
import BrandRankings from "@/components/BrandRankings";

export default function CategoryIntelPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedCategory, setSelectedCategory] = useState("");
  const [landscape, setLandscape] = useState<CategoryLandscape | null>(null);
  const [whitespace, setWhitespace] = useState<CategoryWhitespace | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchCategories().then((res) => setCategories(res.data));
  }, []);

  useEffect(() => {
    if (!selectedCategory) {
      setLandscape(null);
      setWhitespace(null);
      return;
    }
    setLoading(true);
    Promise.all([
      fetchCategoryLandscape(selectedCategory),
      fetchCategoryWhitespace(selectedCategory),
    ])
      .then(([landscapeRes, whitespaceRes]) => {
        setLandscape(landscapeRes.data);
        setWhitespace(whitespaceRes.data);
      })
      .finally(() => setLoading(false));
  }, [selectedCategory]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">Category Intel</h1>
        <p className="text-sm text-gray-500 mt-1">
          Analyze category landscapes, identify whitespace opportunities
        </p>
      </div>

      {/* Category selector grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {categories.map((cat) => (
          <button
            key={cat.name}
            onClick={() => setSelectedCategory(cat.name)}
            className={`rounded-xl border p-4 text-left transition-colors ${
              selectedCategory === cat.name
                ? "border-emerald-500/40 bg-emerald-500/10"
                : "border-gray-700 bg-gray-800/60 hover:border-gray-600"
            }`}
          >
            <div
              className={`text-sm font-medium ${
                selectedCategory === cat.name
                  ? "text-emerald-400"
                  : "text-gray-300"
              }`}
            >
              {cat.name}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              {cat.product_count} products · {cat.brand_count} brands
            </div>
          </button>
        ))}
      </div>

      {/* Loading */}
      {loading && (
        <div className="space-y-4">
          <div className="h-48 rounded-xl bg-gray-900 animate-pulse" />
          <div className="h-64 rounded-xl bg-gray-900 animate-pulse" />
        </div>
      )}

      {/* Results */}
      {landscape && whitespace && !loading && (
        <>
          {/* Overview stats */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-gray-700 bg-gray-800/60 p-4">
              <div className="text-xs text-gray-400 mb-1">Total Brands</div>
              <div className="text-2xl font-bold text-gray-100">
                {landscape.total_brands}
              </div>
            </div>
            <div className="rounded-xl border border-gray-700 bg-gray-800/60 p-4">
              <div className="text-xs text-gray-400 mb-1">Total SKUs</div>
              <div className="text-2xl font-bold text-gray-100">
                {landscape.total_skus}
              </div>
            </div>
            <div className="rounded-xl border border-gray-700 bg-gray-800/60 p-4">
              <div className="text-xs text-gray-400 mb-1">Price Range</div>
              <div className="text-2xl font-bold text-gray-100">
                ₹{landscape.price_range.min}–{landscape.price_range.max}
              </div>
            </div>
            <div className="rounded-xl border border-gray-700 bg-gray-800/60 p-4">
              <div className="text-xs text-gray-400 mb-1">
                Sparse Price Bands
              </div>
              <div className="text-2xl font-bold text-emerald-400">
                {whitespace.price_bands.filter((b) => b.density === "sparse").length}
              </div>
            </div>
          </div>

          {/* Bubble chart */}
          <BubbleChart
            brands={landscape.brands}
            title="Brand Landscape — Price vs Discount"
          />

          {/* Whitespace */}
          <WhitespaceAnalysis data={whitespace} />

          {/* Rankings table */}
          <BrandRankings brands={landscape.brands} />
        </>
      )}
    </div>
  );
}
