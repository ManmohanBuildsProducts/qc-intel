export interface Brand {
  name: string;
  product_count: number;
  categories: string[];
}

export interface Category {
  name: string;
  product_count: number;
  brand_count: number;
}

export interface Product {
  id: number;
  platform: string;
  name: string;
  brand: string;
  category: string;
  unit: string;
  price: number | null;
  mrp: number | null;
  in_stock: boolean;
}

export interface DashboardStats {
  products: number;
  brands: number;
  categories: number;
  platforms: number;
  last_scrape: string | null;
}

export interface ChartDataset {
  label: string;
  data: number[];
  backgroundColor?: string[] | string;
  borderColor?: string;
  borderWidth?: number;
}

export interface ChartData {
  labels: string[];
  datasets: ChartDataset[];
}

export interface ReportResponse {
  content: string;
  brand: string;
  category: string;
  sections: string[];
  product_count: number;
  platform_count: number;
  is_opportunity_mode: boolean;
}

export interface BrandMetricsShare {
  sku_count: number;
  category_total: number;
  share_pct: number;
  rank: number;
}

export interface BrandMetricsHistogram {
  labels: string[];
  brand: number[];
  category: number[];
}

export interface BrandMetricsMrpTiers {
  labels: string[];
  brand: number[];
  category: number[];
  budget_threshold: number;
  premium_threshold: number;
}

export interface BrandMetricsDiscount {
  brand_avg: number;
  category_avg: number;
}

export interface BrandMetricsPlatformCoverage {
  by_platform: Record<string, number>;
  cross_platform_count: number;
  total: number;
}

export interface PriceParityRow {
  canonical_name: string;
  blinkit_price: number;
  zepto_price: number;
  delta: number;
  delta_pct: number;
}

export interface CompetitorRow {
  brand: string;
  sku_count: number;
  is_target: boolean;
}

export interface BrandMetrics {
  share: BrandMetricsShare;
  price_histogram: BrandMetricsHistogram;
  mrp_tiers: BrandMetricsMrpTiers;
  discount: BrandMetricsDiscount;
  platform_coverage: BrandMetricsPlatformCoverage;
  price_parity: PriceParityRow[];
  all_competitors: CompetitorRow[];
  canonical_competitors: { brand: string }[];
}

export interface ApiResponse<T> {
  data: T;
}

export interface PaginatedResponse<T> {
  data: T[];
  meta: {
    total: number;
    page: number;
    per_page: number;
  };
}
