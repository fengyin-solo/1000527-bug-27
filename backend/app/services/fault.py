"""故障登记业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.store import store

MODULE = "fault"
REQUIRED_FIELDS = ["故障编号", "发生设备", "故障现象"]
GRADING_FIELDS = ["严重等级", "定级依据", "处理期限"]
STATUS_ORDER = ["待定级", "已定级", "处置中", "已恢复", "已挂起"]
ACTION_RULES = {"确认定级": "已定级", "提交恢复": "已恢复", "挂起故障": "已挂起"}
NEGATIVE_ACTIONS = []

# 定级链路：严重等级决定处理期限与定级依据，由服务端统一推算，
# 页面只展示服务端结论，避免两边口径不一致。
GRADE_RULES = {
    "一级": {"期限天数": 1, "定级依据": "《信号设备故障定级办法》一级：危及行车安全，24小时内办结"},
    "二级": {"期限天数": 3, "定级依据": "《信号设备故障定级办法》二级：影响设备正常使用，3日内办结"},
    "三级": {"期限天数": 7, "定级依据": "《信号设备故障定级办法》三级：一般设备故障，7日内办结"},
}


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

    def stats(self) -> list[dict[str, Any]]:
        """看板口径：超期未闭环只统计待处理（pending）且处理期限已过的故障。"""
        rows = store.rows(MODULE)
        today = date.today().isoformat()
        overdue = sum(
            1
            for row in rows
            if row.get("pending")
            and str(row.get("处理期限") or "")
            and str(row.get("处理期限")) < today
        )
        return [
            {"label": "待定级故障", "value": sum(1 for row in rows if row.get("status") == "待定级")},
            {"label": "处置中故障", "value": sum(1 for row in rows if row.get("status") == "处置中")},
            {"label": "今日恢复数", "value": sum(1 for row in rows if row.get("恢复时间") == today)},
            {"label": "超期未闭环", "value": overdue},
        ]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        problems: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            problems.append(f"缺少必填字段：{'、'.join(missing)}")
        grade_error = self._check_grade(values)
        if grade_error:
            problems.append(grade_error)
        if problems:
            return None, problems
        optional = [field for field in ("影响范围", "发生时间", "报告人") if values.get(field) is not None]
        existing = self._find_pending_duplicate(values)
        if existing is not None:
            # 同一条故障重复定级：待定级记录只保留最新一次结论，不再新增行
            existing.update({field: values.get(field) for field in REQUIRED_FIELDS})
            existing.update({field: values.get(field) for field in optional})
            self._apply_grading(existing, values)
            return existing, []
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry.update({field: values.get(field) for field in optional})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        self._apply_grading(entry, values)
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"设备故障 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于故障登记可执行范围"
        values = values or {}
        if action == "确认定级":
            grade_error = self._check_grade(values)
            if grade_error:
                return None, grade_error
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == "确认定级":
            self._apply_grading(entry, values)
        if action == "挂起故障":
            # 挂起即未恢复，清掉残留的恢复时间
            entry["恢复时间"] = None
        return entry, f"设备故障已{action}"

    def _find_pending_duplicate(self, values: dict[str, Any]) -> dict[str, Any] | None:
        """待定级故障按故障编号（或发生设备+故障现象）去重，命中即复用原行。"""
        code = str(values.get("故障编号") or "").strip()
        device = str(values.get("发生设备") or "").strip()
        symptom = str(values.get("故障现象") or "").strip()
        for row in store.rows(MODULE):
            if row.get("status") != STATUS_ORDER[0]:
                continue
            same_code = code and str(row.get("故障编号", "")).strip() == code
            same_fault = (
                device
                and symptom
                and str(row.get("发生设备", "")).strip() == device
                and str(row.get("故障现象", "")).strip() == symptom
            )
            if same_code or same_fault:
                return row
        return None

    def _check_grade(self, values: dict[str, Any]) -> str | None:
        grade = str(values.get("严重等级") or "").strip()
        if grade and grade not in GRADE_RULES:
            return f"严重等级「{grade}」不在定级范围内（{'、'.join(GRADE_RULES)}）"
        return None

    def _apply_grading(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        """服务端按严重等级推算定级依据与处理期限，保证三者口径一致。"""
        grade = str(values.get("严重等级") or "").strip()
        if not grade:
            return
        rule = GRADE_RULES[grade]
        entry["严重等级"] = grade
        entry["定级依据"] = rule["定级依据"]
        base = self._parse_date(entry.get("发生时间")) or date.today()
        entry["处理期限"] = (base + timedelta(days=int(rule["期限天数"]))).isoformat()

    @staticmethod
    def _parse_date(raw: Any) -> date | None:
        try:
            return date.fromisoformat(str(raw or "").strip())
        except ValueError:
            return None
