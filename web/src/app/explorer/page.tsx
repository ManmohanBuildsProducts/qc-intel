"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import FilterBar from "@/components/FilterBar";
import ProductTable from "@/components/ProductTable";
import PriceDistributionChart from "@/components/charts/PriceDistributionChart";
import { fetchProducts, fetchChartData } from "@/lib/api";
import type { Product, ChartData } from "@/types";

export default function ExplorerPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState({
    brand: "",
    category: "",
    platform: "",
  });
  const [priceChart, setPriceChart] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(true);

  const perPage = 20;
  const totalPages = Math.max(1, Math.ceil(total / perPage));

  useEffect(() => {
    setLoading(true);
    fetchProducts({
      page,
      per_page: perPage,
      brand: filters.brand || undefined,
      category: filters.category || undefined,
      platform: filters.platform ? filters.platform.toLowerCase() : undefined,
    })
      .then((res) => {
        setProducts(res.data);
        setTotal(res.meta.total);
      })
      .catch(() => setProducts([]))
      .finally(() => setLoading(false));
  }, [page, filters]);

  useEffect(() => {
    if (filters.category) {
      fetchChartData("price-distribution", { category: filters.category })
        .then((res) => setPriceChart(res.data))
        .catch(() => setPriceChart(null));
    } else {
      setPriceChart(null);
    }
  }, [filters.category]);

  const handleFilterChange = useCallback(
    (f: { brand: string; category: string; platform: string }) => {
      setFilters(f);
      setPage(1);
    },
    []
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-100">Data Explorer</h2>
        <p className="text-sm text-gray-400">
          Browse and filter product data across platforms.{" "}
          <Link
            href="/brand"
            className="text-emerald-500 hover:text-emerald-400"
          >
            Brand HQ
          </Link>{" "}
          for competitive analysis.
        </p>
      </div>

      <FilterBar onFilterChange={handleFilterChange} />

      {priceChart && <PriceDistributionChart data={priceChart} />}

      {loading ? (
        <div className="h-64 animate-pulse rounded-xl border border-gray-800 bg-gray-900" />
      ) : (
        <ProductTable
          products={products}
          page={page}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      )}
    </div>
  );
}
