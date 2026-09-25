"""故障登记接口：维护设备故障，覆盖确认定级、提交恢复、挂起故障等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.fault import FaultService

router = APIRouter(prefix="/api/fault", tags=["故障登记"])

service = FaultService()

LIST_FIELDS = ["故障编号", "发生设备", "故障现象", "严重等级", "定级依据", "处理期限", "影响范围", "发生时间", "报告人", "恢复时间", "故障状态"]
STATUSES = ["待定级", "已定级", "处置中", "已恢复", "已挂起"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按故障编号检索"),
    status: str | None = Query(default=None, description="待定级、已定级、处置中、已恢复、已挂起"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按故障编号与状态过滤故障登记列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats() -> dict[str, Any]:
    """故障看板：待定级、处置中与超期未闭环（按待处理口径）数量，以及定级等级选项。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出故障登记清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "fault", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条设备故障明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"设备故障 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条设备故障，缺字段时说明原因而不是静默丢弃。

    同一故障编号且故障现象未变的待定级记录会被原地更新，只保留最新一次定级结论。
    """
    entry, missing, created = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    message = "设备故障已登记" if created else "设备故障已更新为最新定级结论"
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条设备故障执行确认定级、提交恢复、挂起故障；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
