"""ComplianceScan 规则引擎 — ScanRule 抽象基类 + 注册表 + MVP 规则实现。

扩展模式：编写 ``ScanRule`` 子类，调用
``rule_registry.register(MyRule())`` 即可激活。无需修改 API schema
或前端。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ScanTarget, ScanVerdictStatus


@dataclass
class ScanVerdict:
    """单条规则的检查结论。"""

    rule_id: str
    status: ScanVerdictStatus
    detail: str


class ScanRule(ABC):
    """抽象合规规则 — 所有规则均继承此类。

    子类设置类级别属性并实现 ``check()`` 方法。
    """

    rule_id: str
    name: str
    description: str
    target_type: str  # ScanTarget 值

    @abstractmethod
    async def check(self, db: AsyncSession, target_id: str) -> ScanVerdict:
        """对目标实体执行此规则。

        必须是纯读取 — 不得修改状态。
        """
        ...


class RuleRegistry:
    """可插拔规则容器。规则在模块导入时注册。"""

    def __init__(self) -> None:
        self._rules: dict[str, ScanRule] = {}

    def register(self, rule: ScanRule) -> None:
        """注册规则实例（通常在导入时调用）。"""
        self._rules[rule.rule_id] = rule

    def for_target(self, target_type: str) -> list[ScanRule]:
        """返回所有 ``target_type`` 匹配的规则。"""
        return [r for r in self._rules.values() if r.target_type == target_type]

    def __len__(self) -> int:
        return len(self._rules)


# 模块级单例
rule_registry = RuleRegistry()


# ── R1: task.verification_exists ────────────────────────


class TaskVerificationExistsRule(ScanRule):
    """Task 必须定义至少一个验证条件。"""

    rule_id = "task.verification_exists"
    name = "Task Verification Exists"
    description = "Task must define at least one verification condition before completion"
    target_type = ScanTarget.TASK

    async def check(self, db: AsyncSession, target_id: str) -> ScanVerdict:
        from src.constants import ScanVerdictStatus
        from src.models.task import Task

        task = await db.get(Task, target_id)
        if task is None:
            return ScanVerdict(self.rule_id, ScanVerdictStatus.FAIL, "Task not found")

        # 预加载 verifications 关联
        await db.refresh(task, ["verifications"])

        if task.verifications and len(task.verifications) > 0:
            return ScanVerdict(
                self.rule_id,
                ScanVerdictStatus.PASS,
                f"Task has {len(task.verifications)} verification condition(s)",
            )
        return ScanVerdict(
            self.rule_id, ScanVerdictStatus.FAIL, "Task has no verification conditions defined"
        )


# ── R3: batch.ownership_complete ────────────────────────


class BatchOwnershipCompleteRule(ScanRule):
    """Batch 中所有 Task 必须已分配负责人。"""

    rule_id = "batch.ownership_complete"
    name = "Batch Ownership Complete"
    description = "Every task in a batch must have an owner (member or worker)"
    target_type = ScanTarget.BATCH

    async def check(self, db: AsyncSession, target_id: str) -> ScanVerdict:
        from src.models.batch import Batch
        from src.models.task import Task

        batch = await db.get(Batch, target_id)
        if batch is None:
            return ScanVerdict(self.rule_id, ScanVerdictStatus.FAIL, "Batch not found")

        result = await db.execute(
            select(Task).where(Task.batch_id == target_id)
        )
        tasks = result.scalars().all()
        total = len(tasks)

        if total == 0:
            return ScanVerdict(
                self.rule_id, ScanVerdictStatus.PASS, "Batch has no tasks — nothing to check"
            )

        owned = sum(1 for t in tasks if t.owner_id is not None)
        unowned = total - owned

        if unowned == 0:
            return ScanVerdict(
                self.rule_id, ScanVerdictStatus.PASS, f"All {owned} task(s) have owners assigned"
            )
        if owned == 0:
            return ScanVerdict(
                self.rule_id,
                ScanVerdictStatus.FAIL,
                f"None of {total} task(s) have owners assigned",
            )
        return ScanVerdict(
            self.rule_id,
            ScanVerdictStatus.WARN,
            f"{owned}/{total} task(s) have owners, {unowned} unowned",
        )


# ── Bootstrap: 注册 MVP 规则 ────────────────────────

rule_registry.register(TaskVerificationExistsRule())
rule_registry.register(BatchOwnershipCompleteRule())
# 远期 R2: rule_registry.register(SkillProtocolConsistencyRule())
# 远期 R4: rule_registry.register(WorkerCapabilityDeclaredRule())
