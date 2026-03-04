from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import pytz
from dateutil.rrule import rrulestr
from ics import Calendar


SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
logger = logging.getLogger(__name__)


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

        window_start = SHANGHAI_TZ.localize(datetime.strptime(start_date, "%Y-%m-%d")) - timedelta(days=7)
        window_end = window_start + timedelta(days=200)

        seen: Set[Tuple[str, datetime, datetime]] = set()

        for ev in cal.events:
            begin_dt = self._fix_tz(ev.begin.datetime)
            end_dt = self._fix_tz(ev.end.datetime)
            duration = end_dt - begin_dt

            rrule_value = None
            for line in ev.extra:
                if hasattr(line, "name") and line.name == "RRULE":
                    rrule_value = line.value
                    break

            if rrule_value:
                naive_start = begin_dt.replace(tzinfo=None)
                try:
                    rule = rrulestr(f"RRULE:{rrule_value}", dtstart=naive_start)
                except Exception:
                    logger.debug("Failed to parse RRULE for '%s': %s", ev.name, rrule_value)
                    self._add_event(seen, ev.name, begin_dt, end_dt, window_start, window_end)
                    continue
                for dt in rule:
                    occ_begin = SHANGHAI_TZ.localize(dt)
                    if occ_begin > window_end:
                        break
                    occ_end = occ_begin + duration
                    self._add_event(seen, ev.name, occ_begin, occ_end, window_start, window_end)
            else:
                self._add_event(seen, ev.name, begin_dt, end_dt, window_start, window_end)

        self._events.sort(key=lambda e: e.begin)
        logger.debug("ICS loaded: %d event occurrences in semester window", len(self._events))

    def _add_event(
        self, seen: Set[Tuple[str, datetime, datetime]],
        name: Any, begin: datetime, end: datetime,
        window_start: datetime, window_end: datetime,
    ) -> None:
        if not (window_start <= begin <= window_end):
            return
        key = (str(name or "").strip(), begin, end)
        if key in seen:
            return
        seen.add(key)
        self._events.append(ParsedEvent(name=key[0], begin=begin, end=end))

    @staticmethod
    def _fix_tz(dt: datetime) -> datetime:
        """ics 库将无时区的浮动时间默认为 UTC，需重新解释为上海时间。"""
        if dt.tzinfo is None or dt.utcoffset() == timedelta(0):
            return SHANGHAI_TZ.localize(dt.replace(tzinfo=None))
        return dt.astimezone(SHANGHAI_TZ)

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


