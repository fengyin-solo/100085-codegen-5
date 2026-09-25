"""货主授信规则引擎。

规则口径（演示模型，金额单位：元，账期单位：天）：

* 授信额度 ``授信额度`` 与允许的结算周期 ``允许结算周期`` 维护在货主档案上；
* 货主当前已占用额度 = 在途装卸作业的预估金额合计
  + 结算状态未到「已收款」的结算单应收未收合计；
* 申请新作业时：``已占用 + 本单预估金额`` 超过授信额度即拦截，
  或存在「应收未收且已超过货主允许结算周期」的结算单（逾期未结）即拦截；
* 额度/账期调整后，对该货主全部在途作业重新判定并打标 ``授信异常``。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.store import store

CUSTOMER_MODULE = "customer"
LOADING_MODULE = "loading"
SETTLE_MODULE = "settle"

# 装卸作业进入「已完成」即视为已完工、不再占用在途额度
LOADING_INTRANSIT_STATUSES = {"待开工", "作业中", "待复核"}
# 结算单到「已收款」才算结清；「有争议」的单子挂起处理，不参与自动拦截
SETTLE_UNPAID_STATUSES = {"待核对", "核对中", "已确认"}

ALLOWED_PERIODS_DAYS = [7, 15, 30, 60, 90]


# ---------- 基础解析 ----------

def parse_money(value: Any) -> Decimal:
    """把表单里的金额解析成两位小数；空值/非数字按 0 处理。"""
    if value is None or str(value).strip() == "":
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", "").strip()).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0")


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def money(value: Any) -> float:
    return float(parse_money(value))


# ---------- 货主与账期 ----------

def find_customer_by_code(code: str) -> dict[str, Any] | None:
    code = str(code or "").strip()
    if not code:
        return None
    for row in store.rows(CUSTOMER_MODULE):
        if str(row.get("客户编码", "")).strip() == code:
            return row
    return None


def allowed_period_days(customer: dict[str, Any]) -> int | None:
    raw = customer.get("允许结算周期")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return None


def bill_due_date(bill: dict[str, Any], days: int | None) -> date | None:
    """结算单应结日期 = 开单日期 + 货主允许结算周期。"""
    opened = parse_date(bill.get("开单日期"))
    if opened is None or days is None:
        return None
    return opened.fromordinal(opened.toordinal() + days)


def overdue_days(bill: dict[str, Any], customer: dict[str, Any], *, today: date | None = None) -> int:
    """逾期天数；未逾期或无法判定账期时返回 0。"""
    days = allowed_period_days(customer)
    due = bill_due_date(bill, days)
    if due is None:
        return 0
    today = today or date.today()
    return max((today - due).days, 0)


# ---------- 额度占用 ----------

def intransit_jobs(customer_code: str) -> list[dict[str, Any]]:
    return [
        row
        for row in store.rows(LOADING_MODULE)
        if str(row.get("客户编码", "")).strip() == str(customer_code).strip()
        and row.get("status") in LOADING_INTRANSIT_STATUSES
    ]


def unpaid_bills(customer_code: str) -> list[dict[str, Any]]:
    return [
        row
        for row in store.rows(SETTLE_MODULE)
        if str(row.get("客户编码", "")).strip() == str(customer_code).strip()
        and row.get("status") in SETTLE_UNPAID_STATUSES
    ]


def credit_usage(customer_code: str) -> dict[str, float]:
    """汇总货主当前已占用额度：在途作业与未结结算单分别列示。"""
    jobs_total = sum((parse_money(row.get("预估金额")) for row in intransit_jobs(customer_code)), Decimal("0"))
    bills_total = sum(
        (
            parse_money(row.get("应收金额")) - parse_money(row.get("已收金额"))
            for row in unpaid_bills(customer_code)
        ),
        Decimal("0"),
    )
    return {
        "在途作业占用": money(jobs_total),
        "未结结算单占用": money(bills_total),
        "已占用额度": money(jobs_total + bills_total),
    }


def first_overdue_bill(customer: dict[str, Any], *, today: date | None = None) -> dict[str, Any] | None:
    """取最早逾期（逾期天数最多）的未结结算单。"""
    overdue = [
        bill
        for bill in unpaid_bills(customer.get("客户编码", ""))
        if overdue_days(bill, customer, today=today) > 0
    ]
    if not overdue:
        return None
    return max(overdue, key=lambda bill: overdue_days(bill, customer, today=today))


def bill_view(bill: dict[str, Any], customer: dict[str, Any] | None = None, *, today: date | None = None) -> dict[str, Any]:
    """给结算单行补上账期截止、逾期天数等派生字段。"""
    view = dict(bill)
    if customer is not None:
        days = allowed_period_days(customer)
        due = bill_due_date(bill, days)
        late = overdue_days(bill, customer, today=today)
        view["账期截止日"] = due.isoformat() if due else ""
        view["逾期天数"] = late
        view["应收未收金额"] = money(parse_money(bill.get("应收金额")) - parse_money(bill.get("已收金额")))
        view["授信异常"] = (
            str(bill.get("status", "")) in SETTLE_UNPAID_STATUSES and late > 0
        )
    return view


# ---------- 申请作业判定 ----------

def evaluate_application(
    customer: dict[str, Any],
    amount: Decimal | float,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """申请作业时的授信判定；拦截时同时给出超额金额与逾期单。"""
    today = today or date.today()
    requested = parse_money(amount)
    limit = parse_money(customer.get("授信额度"))
    usage = credit_usage(customer.get("客户编码", ""))
    occupied = parse_money(usage["已占用额度"])
    projected = occupied + requested
    over = (projected - limit).quantize(Decimal("0.01"))

    overdue = first_overdue_bill(customer, today=today)

    result: dict[str, Any] = {
        "allowed": over <= 0 and overdue is None,
        "授信额度": money(limit),
        "已占用额度": money(occupied),
        "本单金额": money(requested),
        "申请后占用": money(projected),
        "剩余额度": money(limit - occupied),
        "超额金额": money(over) if over > 0 else 0.0,
    }
    if overdue is not None:
        days = allowed_period_days(customer)
        result["逾期单"] = {
            "结算单号": overdue.get("结算单号"),
            "开单日期": overdue.get("开单日期"),
            "账期截止日": (bill_due_date(overdue, days).isoformat() if bill_due_date(overdue, days) else ""),
            "逾期天数": overdue_days(overdue, customer, today=today),
            "应收未收金额": money(parse_money(overdue.get("应收金额")) - parse_money(overdue.get("已收金额"))),
        }
    return result


def reject_message(evaluation: dict[str, Any]) -> str:
    """把判定结果组织成面向操作员的中文说明。"""
    reasons: list[str] = []
    overdue = evaluation.get("逾期单")
    if overdue:
        reasons.append(
            "存在逾期未结结算单 {no}（账期截止 {due}，已逾期 {days} 天，应收未收 ¥{amount:,.2f}）".format(
                no=overdue["结算单号"],
                due=overdue["账期截止日"] or "—",
                days=overdue["逾期天数"],
                amount=overdue["应收未收金额"],
            )
        )
    if evaluation.get("超额金额"):
        reasons.append(
            "超出授信额度 ¥{over:,.2f}（额度 ¥{limit:,.2f}，已占用 ¥{used:,.2f}，"
            "本单 ¥{req:,.2f}，申请后需占用 ¥{projected:,.2f}，剩余额度仅 ¥{remain:,.2f}）".format(
                over=evaluation["超额金额"],
                limit=evaluation["授信额度"],
                used=evaluation["已占用额度"],
                req=evaluation["本单金额"],
                projected=evaluation["申请后占用"],
                remain=evaluation["剩余额度"],
            )
        )
    return "开单被授信规则拦截：" + "；".join(reasons)


# ---------- 在途作业重判 ----------

def _job_reason(
    customer: dict[str, Any],
    usage_total: Decimal,
    *,
    overdue: dict[str, Any] | None,
    limit: Decimal,
    today: date,
) -> str | None:
    if overdue is not None:
        return "货主存在逾期未结结算单 {no}（逾期 {days} 天）".format(
            no=overdue.get("结算单号"),
            days=overdue_days(overdue, customer, today=today),
        )
    if usage_total > limit:
        return "累计占用 ¥{used:,.2f} 已超过授信额度 ¥{limit:,.2f}（超额 ¥{over:,.2f}）".format(
            used=float(usage_total),
            limit=float(limit),
            over=float(usage_total - limit),
        )
    return None


def recheck_customer(customer: dict[str, Any], *, today: date | None = None) -> list[dict[str, Any]]:
    """额度/账期调整后重新判定该货主全部在途作业，返回被标为授信异常的作业明细。"""
    today = today or date.today()
    code = customer.get("客户编码", "")
    limit = parse_money(customer.get("授信额度"))
    overdue = first_overdue_bill(customer, today=today)

    # 同步该货主结算单的异常标记
    for bill in store.rows(SETTLE_MODULE):
        if str(bill.get("客户编码", "")).strip() == str(code).strip():
            bill["abnormal"] = (
                str(bill.get("status", "")) in SETTLE_UNPAID_STATUSES
                and overdue_days(bill, customer, today=today) > 0
            )

    flagged: list[dict[str, Any]] = []
    running = Decimal("0")
    for job in intransit_jobs(code):
        running += parse_money(job.get("预估金额"))
        reason = _job_reason(customer, running, overdue=overdue, limit=limit, today=today)
        job["授信异常"] = reason is not None
        # 装卸任务的异常标记即授信异常；额度恢复后重判会同步解除
        job["abnormal"] = reason is not None
        if reason:
            job["授信异常原因"] = reason
            flagged.append({
                "id": job.get("id"),
                "任务编号": job.get("任务编号"),
                "预估金额": money(job.get("预估金额")),
                "授信异常原因": reason,
            })
        else:
            job["授信异常原因"] = ""
    return flagged


def recheck_all() -> None:
    """服务启动、结算状态变化后对全部货主做一遍在途作业重判。"""
    for customer in store.rows(CUSTOMER_MODULE):
        # 同步结算单的异常标记，供概览/列表统计口径一致
        for bill in store.rows(SETTLE_MODULE):
            if str(bill.get("客户编码", "")).strip() != str(customer.get("客户编码", "")).strip():
                continue
            is_overdue = (
                str(bill.get("status", "")) in SETTLE_UNPAID_STATUSES
                and overdue_days(bill, customer) > 0
            )
            bill["abnormal"] = is_overdue
        recheck_customer(customer)
