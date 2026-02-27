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
