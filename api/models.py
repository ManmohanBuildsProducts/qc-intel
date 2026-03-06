"""Pydantic response models for API endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class BrandItem(BaseModel):
    name: str
    product_count: int
    categories: list[str]


class CategoryItem(BaseModel):
    name: str
    product_count: int
    brand_count: int


class ProductItem(BaseModel):
    id: int
    platform: str
    name: str
    brand: str | None
    category: str
    unit: str | None
    price: float | None
    mrp: float | None
    in_stock: bool | None


class DashboardStats(BaseModel):
    products: int
    brands: int
    categories: int
    platforms: int
    last_scrape: str | None


class ChartDataset(BaseModel):
    label: str
    data: list[float | int]
    backgroundColor: list[str] | str | None = None


class ChartResponse(BaseModel):
    labels: list[str]
    datasets: list[ChartDataset]


class ReportRequest(BaseModel):
    brand: str
    category: str


class ReportData(BaseModel):
    content: str
    brand: str
    category: str
    sections: list[str]
    product_count: int
    platform_count: int
    is_opportunity_mode: bool = False


class ApiResponse(BaseModel):
    data: Any


class PaginatedResponse(BaseModel):
    data: Any
    meta: dict[str, Any]
