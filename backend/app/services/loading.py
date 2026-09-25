"""装卸任务业务规则：开单走货主授信判定，状态流转后同步在途占用。"""
from __future__ import annotations

from typing import Any

from app.services import credit
from app.store import store

MODULE = "loading"
REQUIRED_FIELDS = ["任务编号", "作业类型", "客户编码"]
ALL_FIELDS = REQUIRED_FIELDS + ["关联航次", "计划箱量", "完成箱量", "作业班组", "开始时间", "预估金额"]
STATUS_ORDER = ["待开工", "作业中", "待复核", "已完成"]
ACTION_RULES = {"确认开工": "作业中", "提交复核": "待复核", "确认完成": "已完成"}
NEGATIVE_ACTIONS = []


class LoadingService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        abnormal: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if abnormal is not None:
            rows = [row for row in rows if bool(row.get("授信异常")) == abnormal]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._decorate(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._decorate(entry) if entry else None

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        """补上货主名称与授信占用快照，让列表能直接看出单据为什么被标。"""
        view = dict(row)
        customer = credit.find_customer_by_code(view.get("客户编码", ""))
        view["客户名称"] = customer.get("客户名称", "") if customer else ""
        if customer is not None:
            view["授信额度"] = credit.money(customer.get("授信额度"))
            view["授信占用"] = credit.credit_usage(customer.get("客户编码", ""))["已占用额度"]
        return view

    def create_entry(
        self,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
        """登记装卸任务（开单）。

        依次校验必填字段、货主状态与授信规则；授信不通过时返回结构化拦截明细。
        """
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, None

        code = str(values.get("客户编码")).strip()
        rows = store.rows(MODULE)
        if any(str(row.get("任务编号", "")).strip() == str(values.get("任务编号")).strip() for row in rows):
            return None, [], {"字段错误": {"任务编号": f"任务编号 {values.get('任务编号')} 已存在，请更换"}}

        customer = credit.find_customer_by_code(code)
        if customer is None:
            return None, [], {"字段错误": {"客户编码": f"客户编码 {code} 不存在，请先登记货主或核对编码"}}
        if customer.get("status") != "合作中":
            return None, [], {"拦截类型": "货主状态", "说明": f"货主 {code} 当前状态为「{customer.get('status')}」，仅合作中货主可开单"}

        evaluation = credit.evaluate_application(customer, credit.parse_money(values.get("预估金额")))
        if not evaluation["allowed"]:
            return None, [], {"拦截类型": "授信规则", "说明": credit.reject_message(evaluation), "授信判定": evaluation}

        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ALL_FIELDS:
            if values.get(field) is not None and str(values.get(field)).strip() != "":
                entry[field] = self._normalize(field, values[field])
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["授信异常"] = False
        entry["授信异常原因"] = ""
        rows.append(entry)
        # 新单已计入在途占用，重判一次以保持标记准确
        credit.recheck_customer(customer)
        return self._decorate(entry), [], None

    @staticmethod
    def _normalize(field: str, value: Any) -> Any:
        if field == "预估金额":
            return credit.money(value)
        if field in ("计划箱量", "完成箱量"):
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        return value

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"装卸任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于装卸任务可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        # 完工出库会释放占用，重判该货主其余在途作业
        customer = credit.find_customer_by_code(entry.get("客户编码", ""))
        if customer is not None:
            credit.recheck_customer(customer)
            entry = store.find(MODULE, entry_id) or entry
        return self._decorate(entry), f"装卸任务已{action}"
