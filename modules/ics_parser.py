from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytz
from ics import Calendar


SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")


@dataclass
class ParsedEvent:
    name: str
    begin: datetime  # aware
    end: datetime    # aware


class ICSParser:
    """解析 ICS 并基于时间匹配课程信息。"""

    def __init__(self, ics_path: str, start_date: str) -> None:
        self._events: List[ParsedEvent] = []
        self._semester_start_date: date = self._parse_date(start_date)

        with open(ics_path, "r", encoding="utf-8") as f:
            cal = Calendar(f.read())

        # 展开重复事件：以学期起始日期为中心，向后约 200 天的时间窗
        window_start = SHANGHAI_TZ.localize(datetime.strptime(start_date, "%Y-%m-%d")) - timedelta(days=7)
        window_end = window_start + timedelta(days=200)

        try:
            timeline = cal.timeline
            timeline.start = window_start
            timeline.stop = window_end
            for occ in timeline:
                begin_dt = occ.begin.datetime
                end_dt = occ.end.datetime
                if begin_dt.tzinfo is None:
                    begin_dt = SHANGHAI_TZ.localize(begin_dt)
                if end_dt.tzinfo is None:
                    end_dt = SHANGHAI_TZ.localize(end_dt)
                self._events.append(
                    ParsedEvent(name=str(occ.name or ""), begin=begin_dt, end=end_dt)
                )
        except Exception:
            # 回退：不展开，仅收集显式事件（可能遗漏重复实例）
            for ev in cal.events:
                begin_dt = ev.begin.datetime
                end_dt = ev.end.datetime
                if begin_dt.tzinfo is None:
                    begin_dt = SHANGHAI_TZ.localize(begin_dt)
                if end_dt.tzinfo is None:
                    end_dt = SHANGHAI_TZ.localize(end_dt)
                if window_start <= begin_dt <= window_end:
                    self._events.append(ParsedEvent(name=str(ev.name or ""), begin=begin_dt, end=end_dt))

        # 按时间排序，便于后续匹配
        self._events.sort(key=lambda e: e.begin)

    def _parse_date(self, s: str) -> date:
        return datetime.strptime(s, "%Y-%m-%d").date()

    def _to_aware(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return SHANGHAI_TZ.localize(dt)
        return dt

    def _calc_week_num(self, dt: datetime) -> int:
        delta_days = (dt.date() - self._semester_start_date).days
        return max(1, 1 + delta_days // 7)

    def match_course(self, target_datetime: datetime) -> Optional[Dict[str, Any]]:
        """返回 {'course_name': str, 'week_num': int} 或 None。

        新策略：
        1) 若 target 落在任一事件区间 [begin, end] 内，直接命中该事件；
        2) 否则在所有事件中，计算 target 到每个事件的最近边界距离：
           min(|begin - target|, |end - target|)。若最近距离 ≤ 1 小时则命中；
        3) 否则不匹配。
        """
        if not self._events:
            return None

        target = self._to_aware(target_datetime)

        # 1) 区间内命中
        covering = [ev for ev in self._events if ev.begin <= target <= ev.end]
        if covering:
            covering.sort(key=lambda ev: abs((ev.begin - target).total_seconds()))
            hit = covering[0]
            return {
                "course_name": hit.name.strip(),
                "week_num": self._calc_week_num(target),
            }

        # 2) 最近边界（开始或结束），阈值 1 小时
        def edge_distance_seconds(ev: ParsedEvent) -> float:
            db = abs((ev.begin - target).total_seconds())
            de = abs((ev.end - target).total_seconds())
            return min(db, de)

        closest = min(self._events, key=edge_distance_seconds)
        if edge_distance_seconds(closest) <= 3600.0:
            return {
                "course_name": closest.name.strip(),
                "week_num": self._calc_week_num(target),
            }

        # 3) 不匹配
        return None


