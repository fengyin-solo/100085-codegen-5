"""货主档案业务规则：状态流转、字段校验、授信额度维护与在途作业重判。"""
from __future__ import annotations

from typing import Any

from app.services import credit
from app.store import store

MODULE = "customer"
REQUIRED_FIELDS = ["客户编码", "客户名称", "客户类型"]
# 授信配置随档案一并登记/维护
CREDIT_FIELDS = ["授信额度", "允许结算周期"]
ALL_FIELDS = REQUIRED_FIELDS + ["联系人", "联系电话", "结算方式", "信用等级"] + CREDIT_FIELDS
STATUS_ORDER = ["待审核", "合作中", "已暂停", "已终止"]
ACTION_RULES = {"审核客户": "合作中", "暂停合作": "已暂停", "终止合作": "已终止"}
NEGATIVE_ACTIONS = []


class CustomerService:
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
            rows = [
                row
                for row in rows
                if keyword in str(row.get("客户编码", "")) or keyword in str(row.get("客户名称", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._decorate(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._decorate(entry) if entry else None

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        """补上额度占用、剩余额度与逾期情况，供列表与前端看板直接使用。"""
        view = dict(row)
        usage = credit.credit_usage(row.get("客户编码", ""))
        limit = credit.money(view.get("授信额度"))
        view.update(usage)
        view["剩余额度"] = credit.money(credit.parse_money(limit) - credit.parse_money(usage["已占用额度"]))
        overdue = credit.first_overdue_bill(row)
        view["存在逾期单"] = overdue is not None
        view["逾期结算单号"] = overdue.get("结算单号", "") if overdue else ""
        return view

    def validate_credit_values(
        self,
        values: dict[str, Any],
        *,
        current_code: str | None = None,
    ) -> dict[str, str]:
        """校验授信配置；返回 字段名 -> 错误原因 的映射，空映射表示通过。

        ``current_code`` 用于编辑时排除自身的客户编码。
        """
        field_errors: dict[str, str] = {}

        code = str(values.get("客户编码") or "").strip()
        if code:
            duplicate = credit.find_customer_by_code(code)
            if duplicate is not None and str(duplicate.get("客户编码")) != str(current_code or "").strip():
                field_errors["客户编码"] = f"客户编码 {code} 已被占用，请更换为唯一编码"

        limit_raw = str(values.get("授信额度") if values.get("授信额度") is not None else "").strip()
        if limit_raw:
            try:
                limit = float(limit_raw.replace(",", ""))
            except ValueError:
                field_errors["授信额度"] = "授信额度必须是数字，请重新填写"
            else:
                if limit < 0:
                    field_errors["授信额度"] = f"授信额度不能为负数（当前填写 {limit_raw}），请改为大于等于 0 的金额"

        period_raw = str(values.get("允许结算周期") if values.get("允许结算周期") is not None else "").strip()
        if period_raw:
            try:
                period = int(round(float(period_raw.replace("天", "").strip())))
            except ValueError:
                field_errors["允许结算周期"] = "允许结算周期必须是整数天数"
            else:
                if period <= 0:
                    field_errors["允许结算周期"] = "允许结算周期必须为正整数天数"
                elif period not in credit.ALLOWED_PERIODS_DAYS:
                    options = "、".join(f"{day}天" for day in credit.ALLOWED_PERIODS_DAYS)
                    field_errors["允许结算周期"] = f"允许结算周期仅支持：{options}"
        return field_errors

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], dict[str, str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, {}
        field_errors = self.validate_credit_values(values)
        if field_errors:
            return None, [], field_errors

        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ALL_FIELDS:
            if values.get(field) is not None and str(values.get(field)).strip() != "":
                entry[field] = self._normalize(field, values[field])
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._decorate(entry), [], {}

    def update_credit(
        self,
        entry_id: int,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, dict[str, str], list[dict[str, Any]]]:
        """调整授信额度/账期，随后对在途作业重新判定。

        返回 (货主明细, 成功消息, 字段错误, 被标为不再合规的作业列表)。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"货主 {entry_id} 不存在或已归档", {}, []

        merged = {"客户编码": entry.get("客户编码"), **values}
        field_errors = self.validate_credit_values(merged, current_code=entry.get("客户编码"))
        if field_errors:
            return None, "授信配置校验未通过", field_errors, []

        for field in CREDIT_FIELDS:
            if values.get(field) is not None and str(values.get(field)).strip() != "":
                entry[field] = self._normalize(field, values[field])

        flagged = credit.recheck_customer(entry)
        message = (
            f"授信配置已更新，重判发现 {len(flagged)} 笔在途作业不再合规"
            if flagged
            else "授信配置已更新，在途作业重判全部合规"
        )
        return self._decorate(entry), message, {}, flagged

    @staticmethod
    def _normalize(field: str, value: Any) -> Any:
        if field == "授信额度":
            return credit.money(value)
        if field == "允许结算周期":
            return int(round(float(str(value).replace("天", "").strip())))
        return value

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"货主 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于货主档案可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._decorate(entry), f"货主已{action}"
