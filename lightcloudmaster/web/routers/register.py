"""注册端点（v2.0.0 P3）：POST /api/register（处置表 #2，+协议签署留痕 P4）。

年龄门 / 监护人信号 / 邮箱校验 / 保留期初始化 / 协议签署留痕全部在
services.registration.register_profile（单点），本层只翻译错误与组装响应。
红线：<14 岁数据不处理（RegistrationError → 400），匿名 ID 96 位熵由服务层生成。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

# RegistrationError 与校验纯函数 register() 一起保留在 lightcloudmaster/registration.py 原位
# （服务层只复用不迁移、也不再导出），异常自源头导入；register_profile 才是服务层入口。
from ...registration import RegistrationError
from ...services.registration import register_profile
from ..deps import AppContext, get_ctx
from ..schemas import RegisterReq

router = APIRouter(prefix="/api", tags=["register"])


@router.post("/register")
def api_register(req: RegisterReq, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, str | bool]:
    """注册：成功返回新的匿名 ID；年龄门等校验失败 400（文案由服务层给定，测试锚定）。"""
    try:
        key, _profile = register_profile(
            store=ctx.store,
            privacy=ctx.privacy_store,
            agreements=ctx.agreements,
            age=req.age,
            guardian_contact_available=req.guardian_contact_available,
            dependency_tendency=req.dependency_tendency,
            email=req.email,
        )
    except RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "profile_key": key}
