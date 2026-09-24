"""FastAPI 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI

from .greenwave import compute_windows, offset_diagnostics
from .schemas import (
    GreenWaveRequest,
    OffsetDiagnosticsRequest,
    OffsetDiagnosticsResponse,
    OffsetInterval,
    Window,
)

app = FastAPI(
    title="干线绿波发车窗口 API",
    description=(
        "给定干线上至多 8 个路口的信号周期、相位偏移、周期内绿灯半开区间"
        "（可跨周期零点）及行驶秒数（可选上限 travel_max，表示行驶时间可取"
        "[travel, travel_max] 内任意实数），计算在指定发车范围（<= 3600 秒）"
        "内、对所有可能的行驶时间抵达每个路口均遇绿灯的全部极大半开"
        "发车区间。\n\n"
        "另提供单路口偏移诊断接口 `POST /api/green-wave/offset-diagnostics`："
        "给定一个路口的周期、绿灯相位及 1..2000 条（到达时刻, 实际灯色）"
        "观测，对整数 offset∈[0,cycle) 按 (arrival_time+offset) mod cycle "
        "预测灯色，返回最少错配条数与取到该值的全部极大半开 offset 区间"
        "（周期区间事件扫描，不逐一计算 offset×观测）。"
    ),
    version="1.1.0",
)


@app.get("/health", tags=["系统"], summary="健康检查")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/green-wave/windows",
    response_model=list[Window],
    tags=["绿波"],
    summary="计算全部极大绿波发车窗口",
)
def green_wave_windows(request: GreenWaveRequest) -> list[Window]:
    request.validate_ranges()
    windows = compute_windows(
        intersections=[
            {
                "cycle": item.cycle,
                "offset": item.offset,
                "green_start": item.green_start,
                "green_end": item.green_end,
                "travel": item.travel,
                "travel_max": item.effective_travel_max,
            }
            for item in request.intersections
        ],
        depart_from=request.depart_from,
        depart_to=request.depart_to,
    )
    return [Window(start=start, end=end) for start, end in windows]


@app.post(
    "/api/green-wave/offset-diagnostics",
    response_model=OffsetDiagnosticsResponse,
    tags=["绿波"],
    summary="单路口 offset 诊断：最少错配条数与最优 offset 区间",
)
def green_wave_offset_diagnostics(
    request: OffsetDiagnosticsRequest,
) -> OffsetDiagnosticsResponse:
    request.validate_ranges()
    minimum, intervals = offset_diagnostics(
        cycle=request.cycle,
        green_start=request.green_start,
        green_end=request.green_end,
        observations=(
            (item.arrival_time, item.observed_green)
            for item in request.observations
        ),
    )
    return OffsetDiagnosticsResponse(
        min_mismatches=minimum,
        optimal_intervals=[
            OffsetInterval(start=start, end=end) for start, end in intervals
        ],
    )
