"""故障登记业务规则：状态流转、定级口径与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.store import store

MODULE = "fault"
REQUIRED_FIELDS = ["故障编号", "发生设备", "故障现象"]
OPTIONAL_FIELDS = ["影响范围", "发生时间", "报告人"]
CLASSIFY_FIELDS = ["严重等级", "定级依据", "处理期限"]
STATUS_ORDER = ["待定级", "已定级", "处置中", "已恢复", "已挂起"]
CLOSED_STATUSES = {"已恢复", "已挂起"}
ACTION_RULES = {"确认定级": "已定级", "提交恢复": "已恢复", "挂起故障": "已挂起"}
CLASSIFIABLE_STATUSES = {"待定级", "已定级"}
NEGATIVE_ACTIONS: list[str] = []

# 定级规则：等级、定级依据、处理期限绑在同一条规则里，全链路只认这一份，
# 避免等级与依据、期限错位。
LEVEL_RULES = [
    {"等级": "重大", "依据": "危及行车安全或导致联锁功能失效", "期限天数": 1},
    {"等级": "较大", "依据": "影响正线行车效率或设备功能降级", "期限天数": 3},
    {"等级": "一般", "依据": "局部功能异常，不影响行车组织", "期限天数": 7},
]
DEFAULT_LEVEL = LEVEL_RULES[-1]["等级"]


def _level_rule(level: str) -> dict[str, Any] | None:
    for rule in LEVEL_RULES:
        if rule["等级"] == level:
            return rule
    return None


def _deadline(entry: dict[str, Any], days: int) -> str:
    """以发生时间为基准推算处理期限；发生时间缺失或无法解析时按今天起算。"""
    base: date
    try:
        base = date.fromisoformat(str(entry.get("发生时间") or ""))
    except ValueError:
        base = date.today()
    return (base + timedelta(days=days)).isoformat()


def _apply_classification(entry: dict[str, Any], rule: dict[str, Any]) -> None:
    entry["严重等级"] = rule["等级"]
    entry["定级依据"] = rule["依据"]
    entry["处理期限"] = _deadline(entry, int(rule["期限天数"]))


class FaultService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("故障编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def stats(self) -> dict[str, Any]:
        """看板口径：超期未闭环按待处理（未闭环）口径统计，等级选项随规则下发。"""
        rows = store.rows(MODULE)
        items = [
            {"label": "待定级故障", "value": sum(1 for row in rows if row.get("status") == "待定级")},
            {"label": "处置中故障", "value": sum(1 for row in rows if row.get("status") == "处置中")},
            {"label": "超期未闭环", "value": sum(1 for row in rows if row.get("pending"))},
        ]
        return {"items": items, "levels": [rule["等级"] for rule in LEVEL_RULES]}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False
        rows = store.rows(MODULE)
        # 同一条故障（故障编号一致）且故障现象没变、仍待定级时，重复登记/定级
        # 只保留最新一次结论，在原行上更新，不再追加新行。
        for row in rows:
            if (
                row.get("status") == "待定级"
                and str(row.get("故障编号")) == str(values.get("故障编号"))
                and str(row.get("故障现象")) == str(values.get("故障现象"))
            ):
                for field in OPTIONAL_FIELDS + CLASSIFY_FIELDS:
                    if values.get(field) is not None:
                        row[field] = values.get(field)
                return row, [], False
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry.update({field: values.get(field) for field in OPTIONAL_FIELDS})
        entry.update({field: values.get(field) for field in CLASSIFY_FIELDS})
        entry["恢复时间"] = None
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, [], True

    def run_action(self, entry_id: int, action: str, values: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"设备故障 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于故障登记可执行范围"
        values = values or {}
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if action == "确认定级":
            if entry.get("status") not in CLASSIFIABLE_STATUSES:
                return None, f"设备故障当前状态为「{entry.get('status')}」，不允许确认定级"
            level = str(values.get("严重等级") or entry.get("严重等级") or DEFAULT_LEVEL).strip()
            rule = _level_rule(level)
            if rule is None:
                options = "、".join(item["等级"] for item in LEVEL_RULES)
                return None, f"严重等级「{level}」不在定级规则内，可选：{options}"
            # 重复定级只刷新本条结论，列表不新增行。
            _apply_classification(entry, rule)
        if action == "提交恢复":
            entry["恢复时间"] = date.today().isoformat()
        if action == "挂起故障":
            # 挂起即不再闭环，残留的恢复时间一并清掉。
            entry["恢复时间"] = None
        entry["status"] = target
        entry["pending"] = target not in CLOSED_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"设备故障已{action}"
