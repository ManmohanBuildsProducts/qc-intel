import type {
  Brand,
  Category,
  Product,
  DashboardStats,
  ChartData,
  ReportResponse,
  ApiResponse,
  PaginatedResponse,
} from "@/types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export function fetchBrands(): Promise<ApiResponse<Brand[]>> {
  return apiFetch("/brands");
}

export function fetchCategories(): Promise<ApiResponse<Category[]>> {
  return apiFetch("/categories");
}

export function fetchProducts(params: {
  page?: number;
  per_page?: number;
  brand?: string;
  category?: string;
  platform?: string;
}): Promise<PaginatedResponse<Product>> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.per_page) query.set("per_page", String(params.per_page));
  if (params.brand) query.set("brand", params.brand);
  if (params.category) query.set("category", params.category);
  if (params.platform) query.set("platform", params.platform);
  return apiFetch(`/products?${query.toString()}`);
}

export function fetchDashboardStats(): Promise<ApiResponse<DashboardStats>> {
  return apiFetch("/dashboard/stats");
}

export function fetchChartData(
  endpoint: string,
  params?: Record<string, string>
): Promise<ApiResponse<ChartData>> {
  const query = params
    ? `?${new URLSearchParams(params).toString()}`
    : "";
  return apiFetch(`/charts/${endpoint}${query}`);
}

export function generateReport(
  brand: string,
  category: string
): Promise<ApiResponse<ReportResponse>> {
  return apiFetch("/reports/generate", {
    method: "POST",
    body: JSON.stringify({ brand, category }),
  });
}
