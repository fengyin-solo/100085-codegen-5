"""授信管理接口：维护货主授信额度与结算周期，控制赊账作业的开立、结清与复核。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.credit import CreditService

router = APIRouter(prefix="/api/credit", tags=["授信管理"])

service = CreditService()

LIST_FIELDS = ["客户编码", "客户名称", "授信额度", "允许结算周期"]
JOB_LIST_FIELDS = ["作业单号", "客户编码", "作业内容", "挂账金额", "申请日期", "约定结算日"]
STATUSES = ["生效中", "已冻结"]
JOB_STATUSES = ["在途", "待复核", "已结算"]


@router.get("/summary")
def credit_summary() -> dict[str, Any]:
    """授信看板：授信货主数、在途挂账总额、逾期与待复核作业单数。"""
    return service.summary()


@router.get("/jobs", response_model=PageResult[dict])
def list_jobs(
    keyword: str | None = Query(default=None, description="按客户编码或作业单号检索"),
    status: str | None = Query(default=None, description="在途、待复核、已结算"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """赊账作业单列表；逾期天数按当天动态计算。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_jobs(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/jobs", response_model=ActionResult)
def apply_job(payload: EntryPayload) -> ActionResult:
    """申请赊账作业：存在逾期未结或超出剩余额度时开不了单，并说明超出金额与逾期单号。"""
    job, message = service.apply_job(payload.values)
    if job is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=job)


@router.post("/jobs/{job_id}/actions", response_model=ActionResult)
def run_job_action(job_id: int, payload: EntryPayload) -> ActionResult:
    """对赊账作业执行结清作业；结清后自动复核该货主剩余在途作业。"""
    action = str(payload.values.get("action") or "").strip()
    job, message = service.run_job_action(job_id, action)
    if job is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=job)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出授信档案清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "credit", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按客户编码检索"),
    status: str | None = Query(default=None, description="生效中、已冻结"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """授信档案列表，随额度占用动态计算在途挂账与剩余额度。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记授信档案；客户编码重复或额度为负数时说明原因，并带回冲突档案方便跳转修改。"""
    entry, error, conflict = service.create_entry(payload.values)
    if error:
        return ActionResult(ok=False, message=error, entry=conflict)
    return ActionResult(ok=True, message="授信档案已登记", entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条授信档案；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"授信档案 {entry_id} 不存在或已归档")
    return entry


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """调整额度或结算周期：保存后对在途作业重新判定，不再合规的标记待复核。"""
    entry, message, _ = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条授信档案执行冻结额度、恢复额度；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
