"""请求体模型。"""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class StratumIn(BaseModel):
    stratum_id: str = Field(min_length=1, max_length=128, description="地层编号，全库唯一")
    site: Optional[str] = Field(default=None, max_length=256, description="遗址名称")


class AssertOp(BaseModel):
    """新增断言。relation=earlier_than 表示 stratum_a 早于 stratum_b。"""

    op: Literal["assert"]
    evidence_id: str = Field(min_length=1, max_length=128, description="证据编号，全库唯一（含已撤回）")
    stratum_a: str = Field(min_length=1, max_length=128)
    stratum_b: str = Field(min_length=1, max_length=128)
    relation: Literal["same_period", "earlier_than"]


class RetractOp(BaseModel):
    """撤回断言（按证据编号，仅可撤回生效中的断言）。"""

    op: Literal["retract"]
    evidence_id: str = Field(min_length=1, max_length=128)


Operation = Annotated[Union[AssertOp, RetractOp], Field(discriminator="op")]


class BatchIn(BaseModel):
    """一批断言变更。须携带当前修订号；整批按应用后的最终关系核验，
    任一冲突则整批拒绝、原状态不变；全部通过则原子递增修订号。"""

    expected_revision: int = Field(ge=0, description="当前修订号；不一致则整批拒绝")
    operations: List[Operation] = Field(min_length=1)


class SnapshotIn(BaseModel):
    label: Optional[str] = Field(default=None, max_length=256, description="版本备注")


class DossierIn(BaseModel):
    """专题成果包请求：定版编号 + 至少两个已登记、互不重复的地层编号。

    集合语义：地层顺序无关，同一集合无论输入顺序只得到同一份成果包
    （创建接口幂等，重复请求返回既有包）。空列表 / 含空串 / 含重复地层
    由业务层明确拒绝，不产生半成品。
    """

    version: int = Field(ge=1, description="已存在的定版编号")
    strata: List[str] = Field(description="入选地层编号（至少 2 个不重复值）")


class ProjectionIn(BaseModel):
    """创建推演：固定当前正式修订号、已登记地层与生效断言快照。"""

    label: Optional[str] = Field(default=None, max_length=256, description="推演备注")


class ProjectionBatchIn(BaseModel):
    """推演内的一批断言变更。须携带该推演当前修订号（自 0 起，批次成功后递增）；
    语义与正式批次一致：整批按应用后的最终关系核验，任一冲突则整批拒绝、推演状态不变。"""

    expected_revision: int = Field(ge=0, description="该推演当前修订号；不一致则整批拒绝")
    operations: List[Operation] = Field(min_length=1)
