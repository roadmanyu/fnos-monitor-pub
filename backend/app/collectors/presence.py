"""硬盘插拔去抖。

只比较盘符集合，不读盘片。集合没变时调用方按自己的周期刷新 SMART；
集合变了要连续稳定 disk_plug_debounce_sec 秒才接受，避免热插拔瞬间反复 smartctl。
"""
from __future__ import annotations


class DiskPresenceDebounce:
    def __init__(self) -> None:
        self.stable_ids: tuple[str, ...] | None = None
        self.pending_ids: tuple[str, ...] | None = None
        self.pending_since: float = 0.0

    def consider(self, ids: list[str], now: float, debounce_sec: float) -> str:
        """返回 accept / stable / pending。

        accept：第一次见到，或去抖时间为 0，或新集合已经稳定够久。调用方应立刻采集。
        stable：和已发布的集合相同。调用方按 SMART 周期自行决定要不要采集。
        pending：新集合还在去抖窗口里。调用方保持上一份快照，不要读盘。
        """
        key = tuple(sorted(str(item) for item in ids if item))
        if self.stable_ids is None:
            self.stable_ids = key
            self.pending_ids = None
            return "accept"
        if key == self.stable_ids:
            self.pending_ids = None
            return "stable"
        if debounce_sec <= 0:
            self.stable_ids = key
            self.pending_ids = None
            return "accept"
        if self.pending_ids != key:
            self.pending_ids = key
            self.pending_since = now
            return "pending"
        if now - self.pending_since >= debounce_sec:
            self.stable_ids = key
            self.pending_ids = None
            return "accept"
        return "pending"
