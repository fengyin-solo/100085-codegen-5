"""装卸任务接口：维护装卸任务，覆盖确认开工、提交复核、确认完成等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.loading import LoadingService

router = APIRouter(prefix="/api/loading", tags=["装卸任务"])

service = LoadingService()

LIST_FIELDS = ["任务编号", "关联航次", "作业类型", "计划箱量", "完成箱量", "作业班组", "开始时间", "任务状态"]
STATUSES = ["待开工", "作业中", "待复核", "已完成"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="待开工、作业中、待复核、已完成"),
    abnormal: bool | None = Query(default=None, description="true 只看授信异常的在途作业"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号、状态与授信异常标记过滤装卸任务列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, abnormal=abnormal, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条装卸任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"装卸任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记装卸任务（开单）：超出授信额度或存在逾期未结时拦截，并指出超额金额与逾期单。"""
    entry, missing, detail = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}", details={"字段错误": {field: "该项为必填，请补充" for field in missing}})
    if detail is not None:
        return ActionResult(ok=False, message=str(detail.get("说明", "开单未通过校验")), details=detail)
    return ActionResult(ok=True, message="装卸任务已登记，授信校验通过", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条装卸任务执行确认开工、提交复核、确认完成；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出装卸任务清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "loading", "total": total, "items": items}
