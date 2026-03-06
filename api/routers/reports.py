"""Report endpoint — generate market intelligence reports."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends

from api.deps import get_db
from api.models import ApiResponse, ReportData, ReportRequest
from src.agents.analyst import AnalyticsService

router = APIRouter(prefix="/reports")


@router.post("/generate")
async def generate_report(
    body: ReportRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    service = AnalyticsService(conn)
    report = await service.generate_report(body.brand, body.category)

    content = ""
    report_file = Path(report.report_path)
    if report_file.exists():
        content = report_file.read_text()

    data = ReportData(
        content=content,
        brand=report.brand,
        category=report.category,
        sections=report.sections,
        product_count=report.product_count,
        platform_count=report.platform_count,
        is_opportunity_mode=report.product_count == 0,
    )
    return ApiResponse(data=data.model_dump())
