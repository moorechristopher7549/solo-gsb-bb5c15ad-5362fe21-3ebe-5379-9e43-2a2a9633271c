"""偏移诊断核心算法测试，含随机参数下与逐 offset 暴力实现的对照。"""

import random

from app.greenwave import compute_offset_diagnostics


def obs(arrival_time, observed_green):
    return {"arrival_time": arrival_time, "observed_green": observed_green}


def brute_force(cycle, green_start, green_end, observations):
    """逐 offset 判定的参考实现（仅测试使用）。"""

    def is_green(phase):
        if green_start == green_end:
            return True
        if green_start < green_end:
            return green_start <= phase < green_end
        return phase >= green_start or phase < green_end

    costs = [
        sum(
            1
            for item in observations
            if is_green((item["arrival_time"] + offset) % cycle)
            != item["observed_green"]
        )
        for offset in range(cycle)
    ]
    minimum = min(costs)
    intervals: list[list[int]] = []
    run_start = None
    for offset in range(cycle + 1):
        ok = offset < cycle and costs[offset] == minimum
        if ok:
            if run_start is None:
                run_start = offset
        else:
            if run_start is not None:
                intervals.append([run_start, offset])
                run_start = None
    return minimum, intervals


# ---------- 基本情形 ----------

def test_single_green_observation_plain_green():
    # 绿灯 [20,40)，arrival=0 观测为绿：offset ∈ [20,40) 时零错配
    minimum, intervals = compute_offset_diagnostics(
        60, 20, 40, [obs(0, True)]
    )
    assert minimum == 0
    assert intervals == [[20, 40]]


def test_single_red_observation_is_complement():
    # 观测为红：一致弧为预测红，即绿灯补集
    minimum, intervals = compute_offset_diagnostics(
        60, 20, 40, [obs(0, False)]
    )
    assert minimum == 0
    assert intervals == [[0, 20], [40, 60]]


def test_arrival_time_uses_mod_phase():
    # arrival=80 与 arrival=20 同相位（周期 60），最优弧起点应平移 20
    a = compute_offset_diagnostics(60, 20, 40, [obs(20, True)])
    b = compute_offset_diagnostics(60, 20, 40, [obs(80, True)])
    assert a == b
    assert a == (0, [[0, 20]])


def test_half_open_endpoint_not_green():
    # offset 使 arrival+offset 恰落在绿灯右端点 40 时为红灯（半开）
    # arrival=10：offset=30 时相位 40（红），offset=29 时相位 39（绿）
    minimum, intervals = compute_offset_diagnostics(
        60, 20, 40, [obs(10, True)]
    )
    assert minimum == 0
    assert intervals == [[10, 30]]


# ---------- 跨零点 ----------

def test_wrapping_green_green_observation_split_into_two_segments():
    # 绿灯 [50,60)∪[0,10)，arrival=0 观测为绿：
    # 最优弧跨零点，在 [0,60) 内分段为 [0,10) 与 [50,60)
    minimum, intervals = compute_offset_diagnostics(
        60, 50, 10, [obs(0, True)]
    )
    assert minimum == 0
    assert intervals == [[0, 10], [50, 60]]


def test_wrapping_green_red_observation_is_single_complement():
    minimum, intervals = compute_offset_diagnostics(
        60, 50, 10, [obs(0, False)]
    )
    assert minimum == 0
    assert intervals == [[10, 50]]


def test_wrapping_green_shifted_arc_segments():
    # arrival=5：预测绿弧整体平移后跨零点 → [0,5) ∪ [45,60)
    minimum, intervals = compute_offset_diagnostics(
        60, 50, 10, [obs(5, True)]
    )
    assert minimum == 0
    assert intervals == [[0, 5], [45, 60]]


# ---------- 整周期常绿 ----------

def test_always_green_with_green_observation_matches_everything():
    minimum, intervals = compute_offset_diagnostics(
        60, 10, 10, [obs(3, True), obs(55, True)]
    )
    assert minimum == 0
    assert intervals == [[0, 60]]


def test_always_green_with_red_observation_mismatches_everywhere():
    # 常绿：任何 offset 都预测绿，红观测在全圆上错配，最优仍为 1
    minimum, intervals = compute_offset_diagnostics(
        60, 0, 0, [obs(3, False)]
    )
    assert minimum == 1
    assert intervals == [[0, 60]]


# ---------- 多观测与最优区间 ----------

def test_multiple_observations_intersection_of_arcs():
    # 两条绿观测的一致弧交集为 [20,25)
    observations = [obs(0, True), obs(15, True)]
    minimum, intervals = compute_offset_diagnostics(60, 20, 40, observations)
    assert minimum == 0
    assert intervals == [[20, 25]]


def test_three_observations_mixed_colors():
    # 周期 60、绿灯 [20,40)：
    # arrival=0 绿观测 ⇔ offset ∈ [20,40)
    # arrival=10 红观测 ⇔ offset ∈ [30,50)（预测相位落在绿灯外）
    # arrival=35 红观测 ⇔ offset ∈ [5,25) ∪ [45,60)
    # 三者共同零错配区间为 [30,40)
    observations = [
        obs(0, True),     # 一致 [20,40)
        obs(10, False),   # 一致 [30,50)
        obs(35, False),   # 一致 [5,25) ∪ [45,60)
    ]
    minimum, intervals = compute_offset_diagnostics(60, 20, 40, observations)
    assert minimum == 0
    assert intervals == [[30, 40]]


def test_disjoint_optimal_segments_sorted_by_start():
    # 周期 10、绿灯 [0,5)：
    # arrival=0 绿观测一致 [0,5)；arrival=6 绿观测一致 [4,9)
    # 交集 [4,5) 为 0 错配；offset 0 时错配 1（arrival=6 落到红灯）
    observations = [obs(0, True), obs(6, True)]
    minimum, intervals = compute_offset_diagnostics(10, 0, 5, observations)
    assert minimum == 0
    assert intervals == [[4, 5]]


def test_cycle_one_boundary():
    assert compute_offset_diagnostics(1, 0, 0, [obs(0, True)]) == (0, [[0, 1]])
    assert compute_offset_diagnostics(1, 0, 0, [obs(0, False)]) == (1, [[0, 1]])


def test_tied_optimal_regions_all_returned():
    # 两条互斥的绿观测：arrival=0 要求 offset ∈ [0,3)，arrival=5 要求
    # offset ∈ [5,8)（周期 10、绿灯 [0,3)）；两弧不相交，弧上各错 1 条，
    # 弧外错 2 条，故两个弧都应作为最优区间返回。
    observations = [obs(0, True), obs(5, True)]
    minimum, intervals = compute_offset_diagnostics(10, 0, 3, observations)
    assert minimum == 1
    assert intervals == [[0, 3], [5, 8]]


# ---------- 随机暴力对照 ----------

def test_brute_force_equivalence_on_random_cases():
    random.seed(2026)
    for _ in range(600):
        cycle = random.randint(1, 90)
        green_start = random.randint(0, cycle - 1)
        green_end = random.randint(0, cycle - 1)
        n = random.randint(1, 30)
        observations = [
            obs(random.randint(0, 3 * cycle), random.random() < 0.5)
            for _ in range(n)
        ]
        assert compute_offset_diagnostics(
            cycle, green_start, green_end, observations
        ) == brute_force(cycle, green_start, green_end, observations)


def test_brute_force_equivalence_max_observations():
    random.seed(77)
    cycle = random.randint(500, 2000)
    green_start, green_end = 123, 987
    observations = [
        obs(random.randint(0, 10_000), random.random() < 0.5)
        for _ in range(2000)
    ]
    assert compute_offset_diagnostics(
        cycle, green_start, green_end, observations
    ) == brute_force(cycle, green_start, green_end, observations)
