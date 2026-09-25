"""授信管理业务规则：额度判定、逾期拦截与在途复核都收在这里。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.store import store

MODULE = "credit"
JOB_MODULE = "creditjob"
REQUIRED_FIELDS = ["客户编码", "客户名称", "授信额度", "允许结算周期"]
JOB_REQUIRED_FIELDS = ["客户编码", "作业内容", "挂账金额"]
STATUS_ORDER = ["生效中", "已冻结"]
JOB_STATUS_ORDER = ["在途", "待复核", "已结算"]
ACTION_RULES = {"冻结额度": "已冻结", "恢复额度": "生效中"}
JOB_ACTION_RULES = {"结清作业": "已结算"}
OPEN_JOB_STATUSES = ("在途", "待复核")  # 仍占用授信额度的作业状态


def _parse_amount(value: Any) -> float | None:
    try:
        return round(float(str(value).replace(",", "").strip()), 2)
    except (TypeError, ValueError):
        return None


def _parse_days(value: Any) -> int | None:
    try:
        days = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if days <= 0 or days != int(days):
        return None
    return int(days)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


class CreditService:
    # ---------- 授信档案 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._with_usage(dict(row)) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("客户编码", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._with_usage(dict(row)) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        error, conflict = self._validate_profile(values)
        if error:
            return None, error, conflict
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["客户编码"] = str(values["客户编码"]).strip()
        entry["客户名称"] = str(values["客户名称"]).strip()
        entry["授信额度"] = _parse_amount(values["授信额度"])
        entry["允许结算周期"] = _parse_days(values["允许结算周期"])
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = False
        entry["abnormal"] = False
        rows.append(entry)
        return entry, "", None

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        """调整额度或结算周期：保存后对在途作业重新判定，不再合规的标成待复核。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"授信档案 {entry_id} 不存在或已归档", []
        new_code = str(values.get("客户编码") or entry["客户编码"]).strip()
        if new_code != entry["客户编码"]:
            return None, f"客户编码是授信档案的标识，不能直接改成 {new_code}；如需更换请先冻结原档案再登记新档案", []
        error, _ = self._validate_profile({**values, "客户编码": entry["客户编码"]}, exclude_id=entry_id)
        if error:
            return None, error, []
        entry["客户名称"] = str(values["客户名称"]).strip()
        entry["授信额度"] = _parse_amount(values["授信额度"])
        entry["允许结算周期"] = _parse_days(values["允许结算周期"])
        flagged = self.rejudge_jobs(str(entry["客户编码"]))
        if flagged:
            numbers = "、".join(str(job["作业单号"]) for job in flagged)
            message = f"授信档案已调整，{len(flagged)} 笔在途作业不再合规，已标记待复核：{numbers}"
        else:
            message = "授信档案已调整，在途作业全部合规"
        return entry, message, flagged

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"授信档案 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于授信管理可执行范围"
        entry["status"] = ACTION_RULES[action]
        entry["pending"] = action == "冻结额度"
        entry["abnormal"] = action == "冻结额度"
        return entry, f"授信档案已{action}"

    # ---------- 赊账作业 ----------
    def list_jobs(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._with_overdue(dict(row)) for row in store.rows(JOB_MODULE)]
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("客户编码", "")) or keyword in str(row.get("作业单号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def apply_job(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """申请赊账作业：先拦逾期未结，再按剩余额度判定，两边都过才开单。"""
        missing = [field for field in JOB_REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        code = str(values["客户编码"]).strip()
        profile = self._find_profile(code)
        if profile is None:
            return None, f"货主 {code} 尚未建立授信档案，不能开赊账作业，请先在授信档案中登记额度与结算周期"
        if profile.get("status") == "已冻结":
            return None, f"货主 {code} 的授信额度已冻结，不能开新作业，请先恢复额度"
        amount = _parse_amount(values["挂账金额"])
        if amount is None or amount <= 0:
            return None, f"挂账金额需要填大于 0 的数字（当前填写「{values['挂账金额']}」），请改正后重新提交"
        today = date.today()
        overdue = [job for job in self._open_jobs(code) if self._overdue_days(job, today) > 0]
        if overdue:
            first = min(overdue, key=lambda job: str(job.get("约定结算日") or ""))
            days = self._overdue_days(first, today)
            return None, (
                f"存在逾期未结作业单 {first['作业单号']}"
                f"（约定结算日 {first['约定结算日']}，已逾期 {days} 天，挂账 {first['挂账金额']} 元），"
                f"须先结清该单才能开新作业"
            )
        limit = float(profile.get("授信额度", 0))
        used = round(sum(float(job.get("挂账金额", 0)) for job in self._open_jobs(code)), 2)
        remaining = round(limit - used, 2)
        if amount > remaining:
            return None, (
                f"剩余额度不足：货主 {code} 授信额度 {limit} 元，在途挂账 {used} 元，"
                f"剩余 {remaining} 元，本单挂账 {amount} 元，超出 {round(amount - remaining, 2)} 元"
            )
        rows = store.rows(JOB_MODULE)
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        days = int(profile.get("允许结算周期", 0))
        job = {
            "id": next_id,
            "作业单号": f"CRJOB-{next_id:04d}",
            "客户编码": code,
            "作业内容": str(values["作业内容"]).strip(),
            "挂账金额": amount,
            "申请日期": today.isoformat(),
            "约定结算日": (today + timedelta(days=days)).isoformat(),
            "status": "在途",
            "pending": True,
            "abnormal": False,
        }
        rows.append(job)
        return job, f"作业单 {job['作业单号']} 已开立，约定结算日 {job['约定结算日']}"

    def run_job_action(self, job_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        job = store.find(JOB_MODULE, job_id)
        if job is None:
            return None, f"作业单 {job_id} 不存在或已归档"
        if action not in JOB_ACTION_RULES:
            return None, f"动作「{action}」不属于赊账作业可执行范围"
        if job.get("status") == "已结算":
            return None, f"作业单 {job['作业单号']} 已结清，不能重复结算"
        job["status"] = "已结算"
        job["pending"] = False
        job["abnormal"] = False
        job.pop("复核说明", None)
        flagged = self.rejudge_jobs(str(job.get("客户编码", "")))
        message = f"作业单 {job['作业单号']} 已结清"
        if flagged:
            message += f"，该货主仍有 {len(flagged)} 笔在途作业不合规"
        return job, message

    def rejudge_jobs(self, code: str) -> list[dict[str, Any]]:
        """对在途作业重新判定：累计挂账超额度或已过约定结算日的，标成待复核并写明原因。"""
        profile = self._find_profile(code)
        if profile is None:
            return []
        limit = float(profile.get("授信额度", 0))
        today = date.today()
        flagged: list[dict[str, Any]] = []
        cumulative = 0.0
        for job in sorted(self._open_jobs(code), key=lambda item: int(item.get("id", 0))):
            cumulative = round(cumulative + float(job.get("挂账金额", 0)), 2)
            reasons = []
            if cumulative > limit:
                reasons.append(f"累计在途挂账 {cumulative} 元超出授信额度 {limit} 元")
            days = self._overdue_days(job, today)
            if days > 0:
                reasons.append(f"已过约定结算日 {job.get('约定结算日')}，逾期 {days} 天未结")
            if reasons:
                job["status"] = "待复核"
                job["abnormal"] = True
                job["复核说明"] = "；".join(reasons)
                flagged.append(job)
            else:
                job["status"] = "在途"
                job["abnormal"] = False
                job.pop("复核说明", None)
        return flagged

    def summary(self) -> dict[str, Any]:
        profiles = store.rows(MODULE)
        open_jobs = [job for job in store.rows(JOB_MODULE) if job.get("status") in OPEN_JOB_STATUSES]
        today = date.today()
        return {
            "授信货主": len(profiles),
            "在途挂账": round(sum(float(job.get("挂账金额", 0)) for job in open_jobs), 2),
            "逾期作业单": sum(1 for job in open_jobs if self._overdue_days(job, today) > 0),
            "待复核作业": sum(1 for job in open_jobs if job.get("status") == "待复核"),
        }

    # ---------- 内部工具 ----------
    def _validate_profile(
        self,
        values: dict[str, Any],
        exclude_id: int | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        """返回 (错误说明, 冲突档案)；校验通过时两个都为空。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return f"缺少必填字段：{'、'.join(missing)}", None
        code = str(values["客户编码"]).strip()
        for row in store.rows(MODULE):
            if str(row.get("客户编码", "")) == code and int(row.get("id", 0)) != (exclude_id or 0):
                return (
                    f"客户编码 {code} 已建立授信档案（档案 #{row['id']}），不能重复登记，"
                    f"请前往该档案调整额度或周期"
                ), row
        amount = _parse_amount(values["授信额度"])
        if amount is None:
            return f"授信额度需要填数字（当前填写「{values['授信额度']}」），请改正后重新提交", None
        if amount < 0:
            return f"授信额度不能为负数（当前填写 {amount}），请改为 0 或正数后重新提交", None
        days = _parse_days(values["允许结算周期"])
        if days is None:
            return f"允许结算周期需要填正整数天数（当前填写「{values['允许结算周期']}」），请改正后重新提交", None
        return "", None

    def _find_profile(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("客户编码", "")) == code:
                return row
        return None

    def _open_jobs(self, code: str) -> list[dict[str, Any]]:
        return [
            job for job in store.rows(JOB_MODULE)
            if str(job.get("客户编码", "")) == code and job.get("status") in OPEN_JOB_STATUSES
        ]

    @staticmethod
    def _overdue_days(job: dict[str, Any], today: date) -> int:
        if job.get("status") not in OPEN_JOB_STATUSES:
            return 0
        due = _parse_date(job.get("约定结算日"))
        if due is None:
            return 0
        return max((today - due).days, 0)

    def _with_usage(self, row: dict[str, Any]) -> dict[str, Any]:
        code = str(row.get("客户编码", ""))
        open_jobs = self._open_jobs(code)
        used = round(sum(float(job.get("挂账金额", 0)) for job in open_jobs), 2)
        row["在途挂账"] = used
        row["剩余额度"] = round(float(row.get("授信额度", 0)) - used, 2)
        row["逾期单数"] = sum(1 for job in open_jobs if self._overdue_days(job, date.today()) > 0)
        return row

    def _with_overdue(self, row: dict[str, Any]) -> dict[str, Any]:
        days = self._overdue_days(row, date.today())
        row["是否逾期"] = "是" if days > 0 else "否"
        row["逾期天数"] = days
        return row
