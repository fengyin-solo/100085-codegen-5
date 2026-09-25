"""作业结算接口：维护结算单，覆盖发起核对、确认结算、标记争议等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.settle import SettleService

router = APIRouter(prefix="/api/settle", tags=["作业结算"])

service = SettleService()

LIST_FIELDS = ["结算单号", "结算对象", "结算周期", "作业量", "应收金额", "已收金额", "开票状态", "结算状态"]
STATUSES = ["待核对", "核对中", "已确认", "已收款", "有争议"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按结算单号或客户编码检索"),
    status: str | None = Query(default=None, description="待核对、核对中、已确认、已收款、有争议"),
    overdue_only: bool | None = Query(default=None, description="true 只看逾期未结结算单"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按结算单号、状态与逾期标记过滤作业结算列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, overdue_only=overdue_only, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条结算单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"结算单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记结算单并按货主挂账；编码不存在、日期非法、金额为负时逐字段说明原因。"""
    entry, missing, field_errors = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}", details={"字段错误": {field: "该项为必填，请补充" for field in missing}})
    if field_errors:
        return ActionResult(ok=False, message="结算单登记未通过校验，请按提示修改", details={"字段错误": field_errors})
    return ActionResult(ok=True, message="结算单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条结算单执行发起核对、确认结算、标记争议；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出作业结算清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "settle", "total": total, "items": items}
