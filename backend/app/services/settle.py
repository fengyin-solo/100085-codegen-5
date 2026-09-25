"""作业结算业务规则：按货主挂账、标记逾期未结，收款后释放授信占用。"""
from __future__ import annotations

from typing import Any

from app.services import credit
from app.store import store

MODULE = "settle"
REQUIRED_FIELDS = ["结算单号", "客户编码", "开单日期", "应收金额"]
ALL_FIELDS = REQUIRED_FIELDS + ["结算对象", "结算周期", "作业量", "已收金额", "开票状态"]
STATUS_ORDER = ["待核对", "核对中", "已确认", "已收款", "有争议"]
ACTION_RULES = {"发起核对": "核对中", "确认结算": "已收款", "标记争议": "有争议"}
NEGATIVE_ACTIONS = []


class SettleService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        overdue_only: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("结算单号", "")) or keyword in str(row.get("客户编码", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        decorated = [self._decorate(row) for row in rows]
        if overdue_only:
            decorated = [row for row in decorated if row.get("授信异常")]
        total = len(decorated)
        start = max(page - 1, 0) * size
        return decorated[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._decorate(entry) if entry else None

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        view = dict(row)
        customer = credit.find_customer_by_code(view.get("客户编码", ""))
        if customer is None:
            view.setdefault("授信异常", False)
            return view
        return credit.bill_view(view, customer)

    def create_entry(
        self,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[str], dict[str, str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, {}
        field_errors: dict[str, str] = {}
        code = str(values.get("客户编码")).strip()
        customer = credit.find_customer_by_code(code)
        if customer is None:
            field_errors["客户编码"] = f"客户编码 {code} 不存在，请先登记货主或核对编码"
        if credit.parse_date(values.get("开单日期")) is None:
            field_errors["开单日期"] = "开单日期格式不正确，应为 YYYY-MM-DD"
        if credit.parse_money(values.get("应收金额")) < 0:
            field_errors["应收金额"] = "应收金额不能为负数"
        rows = store.rows(MODULE)
        if any(str(row.get("结算单号", "")).strip() == str(values.get("结算单号")).strip() for row in rows):
            field_errors["结算单号"] = f"结算单号 {values.get('结算单号')} 已存在，请更换"
        if field_errors:
            return None, [], field_errors

        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ALL_FIELDS:
            if values.get(field) is not None and str(values.get(field)).strip() != "":
                entry[field] = self._normalize(field, values[field])
        entry.setdefault("已收金额", 0.0)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        # 新挂账立刻可能形成逾期/超额，重判该货主在途作业
        if customer is not None:
            credit.recheck_customer(customer)
        return self._decorate(entry), [], {}

    @staticmethod
    def _normalize(field: str, value: Any) -> Any:
        if field in ("应收金额", "已收金额"):
            return credit.money(value)
        if field == "作业量":
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        return value

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"结算单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于作业结算可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 确认结算 = 已收款：已收金额补齐到应收，释放占用
        if target == "已收款":
            entry["已收金额"] = credit.money(entry.get("应收金额"))
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        customer = credit.find_customer_by_code(entry.get("客户编码", ""))
        if customer is not None:
            credit.recheck_customer(customer)
            entry = store.find(MODULE, entry_id) or entry
        return self._decorate(entry), f"结算单已{action}"
