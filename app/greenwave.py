"""干线绿波发车窗口核心算法。

所有时间量均为整数秒，路口信号以固定周期循环。

相位约定
--------
对路口 i，给定：

* ``cycle``  : 信号周期 C（秒，正整数）；
* ``offset`` : 相位偏移 o（0 <= o < C），绝对时间 t 在该路口的本地相位为
               ``(t + o) mod C``；
* ``green_start`` / ``green_end`` : 周期内绿灯半开区间端点，取值 [0, C)：
    - g_start < g_end：绿灯为 ``[g_start, g_end)``；
    - g_start > g_end：绿灯跨零点，为 ``[g_start, C) ∪ [0, g_end)``；
    - g_start == g_end：整周期常绿 ``[0, C)``；
* ``travel`` : 从起点到该路口的行驶秒数下限 T（默认即固定行驶时间）；
* ``travel_max`` : 可选的行驶秒数上限，缺省等于 ``travel``。实际行驶时间
  可取闭区间 ``[T, T_max]`` 内的**任意实数**秒，出发窗口必须对其中每一种
  取值都保证遇绿。

出发时刻为 t 时，抵达时刻覆盖闭区间 ``[t + T, t + T_max]``。令波动量
``slack = T_max - T``，在展开（不绕零点）的时间轴上，绿灯半开区间 ``[a,b)``
能容下整个抵达闭区间，当且仅当 ``a <= t+T+o`` 且 ``t+T_max+o < b``，即
绿灯段被右端收缩为 ``[a, b - slack)``（slack >= 段长时该路口永不可行）。
跨零点绿灯须先视为连续时段 ``[g_start, C + g_end)`` **再收缩**，不得拆成
两段分别收缩；整周期常绿不受任何波动影响。每个路口收缩后的可行出发时刻是
一组周期重复的半开整数区间 ``[kC + a - shift, kC + b - shift)``
（shift = (T + o) mod C），再与请求的发车范围
``[depart_from, depart_to)`` 求交；各路口结果两两求交并合并相邻
（端点相接）区间，即得全部极大半开发车窗口。全程只做区间运算，不逐秒试探。
"""

from __future__ import annotations

from typing import Iterable

# 周期上限仅用于防御异常输入，一日之内足够覆盖任何实际信号周期。
MAX_CYCLE = 86_400
MAX_WINDOW_SECONDS = 3_600
MAX_INTERSECTIONS = 8
# 偏移诊断接口接受的观测条数上下限。
MIN_OBSERVATIONS = 1
MAX_OBSERVATIONS = 2_000

Interval = list[int]  # 长度为 2 的半开区间 [start, end)


def local_green_intervals(cycle: int, green_start: int, green_end: int) -> list[Interval]:
    """展开单个周期 [0, C) 内的绿灯半开区间。

    端点相等时视为整周期常绿；跨零点时展开为两段。
    """
    if green_start == green_end:
        return [[0, cycle]]
    if green_start < green_end:
        return [[green_start, green_end]]
    return [[green_start, cycle], [0, green_end]]


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """合并重叠或端点相接的半开区间（[a,b) 与 [b,c) 合并为 [a,c)）。"""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def clip_intervals(
    intervals: Iterable[Interval], lower: int, upper: int
) -> list[Interval]:
    """把半开区间裁剪进 [lower, upper)。"""
    clipped: list[Interval] = []
    for start, end in intervals:
        start = max(start, lower)
        end = min(end, upper)
        if start < end:
            clipped.append([start, end])
    return clipped


def eroded_green_components(
    cycle: int,
    green_start: int,
    green_end: int,
    slack: int,
) -> tuple[bool, list[Interval]]:
    """波动量 slack 下、每个周期内的"连续"绿灯分量（出发轴视角）。

    返回 ``(always_green, components)``：

    * ``green_start == green_end``（整周期常绿）：返回 ``(True, [])``，
      常绿不受行驶时间波动影响；
    * 普通绿灯 ``[g_start, g_end)``：右端收缩为
      ``[g_start, g_end - slack)``，slack >= 绿灯长度时为空；
    * 跨零点绿灯：**先**视为连续时段 ``[g_start, C + g_end)`` **再收缩**
      为 ``[g_start, C + g_end - slack)``（可能长于一个周期）。

    收缩是针对"抵达闭区间整体落入绿灯半开区间"的最坏情形：
    到达最早时刻可压在左端点（含），到达最晚时刻必须严格早于右端点。
    """
    if green_start == green_end:
        return True, []
    if green_start < green_end:
        if slack >= green_end - green_start:
            return False, []
        return False, [[green_start, green_end - slack]]
    # 跨零点：先视为连续的 [g_start, C + g_end)，再做右端收缩。
    extended_end = cycle + green_end - slack
    if extended_end <= green_start:
        return False, []
    return False, [[green_start, extended_end]]


def departure_windows_for_intersection(
    cycle: int,
    offset: int,
    green_start: int,
    green_end: int,
    travel: int,
    depart_from: int,
    depart_to: int,
    travel_max: int | None = None,
) -> list[Interval]:
    """单个路口在 [depart_from, depart_to) 内的全部可行出发区间（已合并）。

    ``travel_max`` 缺省等于 ``travel``（无波动）。行驶时间可能取闭区间
    [travel, travel_max] 内任意实数秒时，只有对所有取值均遇绿的出发时刻
    才会被保留。
    """
    if travel_max is None:
        travel_max = travel
    slack = travel_max - travel
    always_green, components = eroded_green_components(
        cycle, green_start, green_end, slack
    )
    if always_green:
        return [[depart_from, depart_to]]
    # (t + T + o) mod C 与 (t + shift) mod C 等价；slack 只影响绿灯长度。
    shift = (travel + offset) % cycle

    raw: list[Interval] = []
    for local_start, local_end in components:
        # 本地（已收缩）绿灯 [a, b) 对应出发区间 [kC + a - shift, kC + b - shift)。
        # 只需枚举与发车范围有非空交的周期 k：
        #   kC + b - shift > depart_from  ⇔  k > (depart_from - b + shift) / C
        #   kC + a - shift < depart_to    ⇔  k < (depart_to   - a + shift) / C
        k_min = (depart_from - local_end + shift) // cycle + 1
        k_max = -((-(depart_to - local_start + shift)) // cycle) - 1
        for k in range(k_min, k_max + 1):
            base = k * cycle
            raw.append(
                [base + local_start - shift, base + local_end - shift]
            )

    return merge_intervals(clip_intervals(raw, depart_from, depart_to))


def intersect_interval_lists(
    left: list[Interval], right: list[Interval]
) -> list[Interval]:
    """两组各自有序、互不相交的半开区间列表的交集（双指针）。"""
    i = j = 0
    result: list[Interval] = []
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if start < end:
            result.append([start, end])
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return result


def compute_windows(
    intersections: Iterable[dict],
    depart_from: int,
    depart_to: int,
) -> list[Interval]:
    """求所有路口均遇绿灯的全部极大半开发车区间，按起点排序。

    ``intersections`` 中的每个字典包含 cycle / offset / green_start /
    green_end / travel 字段，以及可选的 travel_max 字段（缺省等于 travel，
    表示行驶时间可能取 [travel, travel_max] 内任意实数秒），由 Pydantic 模型
    保证合法。
    """
    common: list[Interval] | None = None
    for item in intersections:
        windows = departure_windows_for_intersection(
            cycle=item["cycle"],
            offset=item["offset"],
            green_start=item["green_start"],
            green_end=item["green_end"],
            travel=item["travel"],
            travel_max=item.get("travel_max"),
            depart_from=depart_from,
            depart_to=depart_to,
        )
        if common is None:
            common = windows
        else:
            common = intersect_interval_lists(common, windows)
        if not common:
            return []
    # 求交不会产生相接区间，最后再合并一次以策安全。
    return merge_intervals(common or [])


# ---------------------------------------------------------------------------
# 偏移诊断：给定单路口观测，求错配最少的整数 offset 及对应的极大区间
# ---------------------------------------------------------------------------


def _add_arc_delta(
    lo: int, hi: int, delta: int, events: dict[int, int], cycle: int
) -> None:
    """在 offset 圆上的半开弧 ``[lo, hi)`` 施加差分 ``delta``。

    约定 ``lo ∈ [0, C)``、``hi = lo + 弧长 ∈ [lo, lo + C]``：

    * ``hi == lo``：空弧，不加任何事件；
    * ``hi <= C``：普通弧 ``[lo, hi)``（``hi == C`` 时为 ``[lo, C)``）；
    * ``hi > C``：跨零点，拆成 ``[lo, C) ∪ [0, hi - C)``。
    """
    if hi == lo:
        return
    if hi <= cycle:
        events[lo] = events.get(lo, 0) + delta
        events[hi] = events.get(hi, 0) - delta
    else:
        events[lo] = events.get(lo, 0) + delta
        events[cycle] = events.get(cycle, 0) - delta
        events[0] = events.get(0, 0) + delta
        events[hi - cycle] = events.get(hi - cycle, 0) - delta


def compute_offset_diagnostics(
    cycle: int,
    green_start: int,
    green_end: int,
    observations: Iterable[dict],
) -> tuple[int, list[Interval]]:
    """求使观测错配条数最少的整数 offset 集合（offset ∈ [0, C)）。

    预测灯色沿用绿灯半开区间语义：本地相位
    ``(arrival_time + offset) mod C`` 落入绿灯半开区间集合即预测为绿，
    ``green_start == green_end`` 时整周期常绿。

    每条观测在 offset 圆上划出一条"与观测灯色一致"的半开弧：

    * 观测为绿（一致 ⇔ 预测绿）：弧长等于绿灯长度，起点
      ``(green_start - arrival_time) mod C``；
    * 观测为红（一致 ⇔ 预测红）：取补集，弧长 ``C - 绿灯长度``。

    每条观测只在不属于其一致弧的 offset 上贡献 1 次错配。所有弧以
    **两个差分事件**（跨零点至多四个）叠加，事件总数 O(观测数)；
    排序后一次扫描即得到每个 offset 分段上的错配条数，复杂度
    ``O(n log n)``，与周期长度无关。扫描结果天然把圆切成常值段，
    取最小值所在的段即为全部极大半开区间；跨零点的极大弧在
    ``[0, C)`` 内以两段表示，按起点排序。

    返回 ``(最少错配条数, 区间列表)``。
    """
    # 绿灯长度（整周期常绿时为 C），以及圆上的绿灯半开弧起点。
    if green_start == green_end:
        green_length = cycle
    elif green_start < green_end:
        green_length = green_end - green_start
    else:
        green_length = cycle - green_start + green_end

    events: dict[int, int] = {}
    n_observations = 0
    for obs in observations:
        n_observations += 1
        arrival_phase = obs["arrival_time"] % cycle
        if obs["observed_green"]:
            # 预测绿弧：相位 x ∈ 绿灯集，offset ≡ x - arrival (mod C)。
            lo = (green_start - arrival_phase) % cycle
            length = green_length
        else:
            # 一致弧为预测红，即预测绿弧在圆上的补集：同样是一条半开弧，
            # 起点恰为预测绿弧的终点。
            lo = (green_start - arrival_phase + green_length) % cycle
            length = cycle - green_length
        # hi 可能 > C，_add_arc_delta 负责把跨零点弧拆成 [lo,C) ∪ [0,hi-C)。
        _add_arc_delta(lo, lo + length, -1, events, cycle)

    # 扫描：每条观测在其一致弧上抵消 1 次错配，故圆上初始错配数为观测总数；
    # events[0] 的差分须先施加，它作用于从 0 开始的那段。positions 含 0 与 C。
    positions = sorted(events)
    if 0 not in positions:
        positions.insert(0, 0)
    if cycle not in positions:
        positions.append(cycle)

    segments: list[tuple[int, Interval]] = []
    mismatches = n_observations + events.get(0, 0)
    prev = 0
    for pos in positions[1:]:
        if pos > prev:
            segments.append((mismatches, [prev, pos]))
        mismatches += events.get(pos, 0)
        prev = pos

    minimum = min(count for count, _ in segments)
    optimal = [interval for count, interval in segments if count == minimum]
    # 整圆弧（常绿观测、红观测一致弧为空等）仍会在事件点产生相接的等值日，
    # 合并端点相接（[a,b) 与 [b,c)）的段，恢复真正的极大区间。注意跨零点
    # 拆分出的首段 [0,b) 与末段 [a,C) 不相接，不会被合并，保留为两段表示。
    return minimum, merge_intervals(optimal)
