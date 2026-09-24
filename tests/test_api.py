import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app, green_wave_windows, offset_diagnostics
from app.schemas import GreenWaveRequest, Intersection, OffsetDiagnosticsRequest


def make_request(payload):
    return GreenWaveRequest.model_validate(payload)


def test_api_returns_windows_payload():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 300,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 30, "travel": 0},
                {"cycle": 60, "offset": 30, "green_start": 0, "green_end": 30, "travel": 30},
            ],
        }
    )
    windows = green_wave_windows(req)
    assert [[w.start, w.end] for w in windows] == [
        [0, 30], [60, 90], [120, 150], [180, 210], [240, 270],
    ]


def test_api_empty_array_on_no_solution():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 10, "travel": 0},
                {"cycle": 60, "offset": 0, "green_start": 20, "green_end": 30, "travel": 0},
            ],
        }
    )
    assert green_wave_windows(req) == []


def test_reject_invalid_cycle():
    with pytest.raises(ValidationError):
        Intersection(cycle=0, offset=0, green_start=0, green_end=10, travel=0)


def test_reject_negative_travel():
    with pytest.raises(ValidationError):
        Intersection(cycle=60, offset=0, green_start=0, green_end=10, travel=-1)


def test_reject_offset_outside_cycle():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 60, "green_start": 0, "green_end": 10, "travel": 0}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_reject_green_endpoint_outside_cycle():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 60, "travel": 0}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_reject_range_over_one_hour():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 3601,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 10, "travel": 0}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_reject_too_many_intersections():
    with pytest.raises(ValidationError):
        make_request(
            {
                "depart_from": 0,
                "depart_to": 60,
                "intersections": [
                    {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 10}
                    for _ in range(9)
                ],
            }
        )


def test_reject_empty_intersections():
    with pytest.raises(ValidationError):
        make_request({"depart_from": 0, "depart_to": 60, "intersections": []})


# ---------- travel_max 波动行驶时间 ----------

def test_travel_max_shrinks_windows():
    # 绿灯 [20,40)，行驶时间 [0,10]：窗口由 20 秒收缩为 10 秒
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 120,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 20,
                 "green_end": 40, "travel": 0, "travel_max": 10}
            ],
        }
    )
    windows = green_wave_windows(req)
    assert [[w.start, w.end] for w in windows] == [[20, 30], [80, 90]]


def test_travel_max_defaults_to_travel():
    base = {
        "cycle": 60, "offset": 0, "green_start": 20, "green_end": 40,
        "travel": 5,
    }
    req = make_request(
        {"depart_from": 0, "depart_to": 120, "intersections": [base]}
    )
    req2 = make_request(
        {"depart_from": 0, "depart_to": 120,
         "intersections": [{**base, "travel_max": 5}]}
    )
    assert green_wave_windows(req) == green_wave_windows(req2)


def test_reject_travel_max_less_than_travel():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 30, "travel": 20, "travel_max": 19}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_reject_travel_max_over_86400():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 30, "travel": 0, "travel_max": 86401}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_travel_max_86400_boundary_accepted():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                # 整周期常绿：波动再大也不受影响
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 0, "travel": 0, "travel_max": 86400}
            ],
        }
    )
    req.validate_ranges()
    windows = green_wave_windows(req)
    assert [[w.start, w.end] for w in windows] == [[0, 60]]


# ---------- 偏移诊断接口 ----------

def make_diag_request(payload):
    return OffsetDiagnosticsRequest.model_validate(payload)


def test_offset_diagnostics_plain_case():
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 20,
            "green_end": 40,
            "observations": [
                {"arrival_time": 0, "observed_green": True},
                {"arrival_time": 15, "observed_green": True},
            ],
        }
    )
    result = offset_diagnostics(req)
    assert result.minimum_mismatches == 0
    assert [[i.start, i.end] for i in result.optimal_offsets] == [[20, 25]]


def test_offset_diagnostics_wrapping_optimal_set():
    # 跨零点最优集合在 [0,cycle) 内分段表示
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 50,
            "green_end": 10,
            "observations": [{"arrival_time": 0, "observed_green": True}],
        }
    )
    result = offset_diagnostics(req)
    assert result.minimum_mismatches == 0
    assert [[i.start, i.end] for i in result.optimal_offsets] == [
        [0, 10], [50, 60]
    ]


def test_offset_diagnostics_always_green_full_cycle():
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 10,
            "green_end": 10,
            "observations": [{"arrival_time": 3, "observed_green": True}],
        }
    )
    result = offset_diagnostics(req)
    assert result.minimum_mismatches == 0
    assert [[i.start, i.end] for i in result.optimal_offsets] == [[0, 60]]


def test_offset_diagnostics_reject_green_endpoint_outside_cycle():
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 0,
            "green_end": 60,
            "observations": [{"arrival_time": 0, "observed_green": True}],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_offset_diagnostics_reject_invalid_cycle():
    with pytest.raises(ValidationError):
        make_diag_request(
            {
                "cycle": 0,
                "green_start": 0,
                "green_end": 0,
                "observations": [{"arrival_time": 0, "observed_green": True}],
            }
        )


def test_offset_diagnostics_reject_empty_observations():
    with pytest.raises(ValidationError):
        make_diag_request(
            {"cycle": 60, "green_start": 0, "green_end": 10, "observations": []}
        )


def test_offset_diagnostics_reject_too_many_observations():
    with pytest.raises(ValidationError):
        make_diag_request(
            {
                "cycle": 60,
                "green_start": 0,
                "green_end": 10,
                "observations": [
                    {"arrival_time": i, "observed_green": True}
                    for i in range(2001)
                ],
            }
        )


def test_offset_diagnostics_accepts_exactly_2000_observations():
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 0,
            "green_end": 0,
            "observations": [
                {"arrival_time": i, "observed_green": True}
                for i in range(2000)
            ],
        }
    )
    req.validate_ranges()
    result = offset_diagnostics(req)
    assert result.minimum_mismatches == 0
    assert [[i.start, i.end] for i in result.optimal_offsets] == [[0, 60]]


def test_offset_diagnostics_http_endpoint():
    client = TestClient(app)
    response = client.post(
        "/api/green-wave/offset-diagnostics",
        json={
            "cycle": 60,
            "green_start": 20,
            "green_end": 40,
            "observations": [{"arrival_time": 0, "observed_green": True}],
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "minimum_mismatches": 0,
        "optimal_offsets": [{"start": 20, "end": 40}],
    }


def test_offset_diagnostics_http_422_payload():
    client = TestClient(app)
    response = client.post(
        "/api/green-wave/offset-diagnostics",
        json={
            "cycle": 60,
            "green_start": 0,
            "green_end": 60,
            "observations": [{"arrival_time": 0, "observed_green": True}],
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("green_end" in item for item in detail)


def test_offset_diagnostics_http_422_missing_field():
    client = TestClient(app)
    response = client.post(
        "/api/green-wave/offset-diagnostics",
        json={"cycle": 60, "green_start": 0, "green_end": 10},
    )
    assert response.status_code == 422


def test_offset_diagnostics_route_in_openapi():
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert "/api/green-wave/offset-diagnostics" in schema["paths"]
    operation = schema["paths"]["/api/green-wave/offset-diagnostics"]["post"]
    assert operation["summary"]
    assert "OffsetDiagnosticsRequest" in schema["components"]["schemas"]
    assert "OffsetDiagnosticsResponse" in schema["components"]["schemas"]
