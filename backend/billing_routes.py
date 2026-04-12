import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .account_store import create_order, get_order, mark_order_paid, set_subscription_plan
from .auth_routes import get_current_user_id


router = APIRouter()


def _require_pay_env(*keys: str) -> None:
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少支付配置: {', '.join(missing)}")


@router.post("/api/billing/wechatpay/create")
async def wechatpay_create(request: Request, amount: int = 1999, title: str = "升级 Pro（月度）"):
    """
    官方直连微信支付：此处先提供可运行的订单接口骨架。
    需要配置：
    - WECHATPAY_MCHID
    - WECHATPAY_SERIAL_NO
    - WECHATPAY_PRIVATE_KEY_PEM
    - WECHATPAY_API_V3_KEY
    - WECHATPAY_APP_ID (如走 JSAPI/H5)
    """
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    _require_pay_env("WECHATPAY_MCHID", "WECHATPAY_SERIAL_NO", "WECHATPAY_PRIVATE_KEY_PEM", "WECHATPAY_API_V3_KEY")

    order = create_order(uid, "wechatpay", int(amount or 0), title=title)

    # TODO: 这里应调用微信支付 v3 下单接口，返回 code_url/mweb_url/prepay_id
    # 先返回占位字段，保证前端流程可串联。
    return {
        "order_id": order["id"],
        "channel": "wechatpay",
        "status": order["status"],
        "amount": order["amount"],
        "pay_url": None,
        "code_url": None,
        "message": "订单已创建（待接入微信支付下单接口）",
    }


@router.post("/api/billing/alipay/create")
async def alipay_create(request: Request, amount: int = 1999, title: str = "升级 Pro（月度）"):
    """
    官方直连支付宝：此处提供订单接口骨架。
    需要配置：
    - ALIPAY_APP_ID
    - ALIPAY_PRIVATE_KEY_PEM
    - ALIPAY_PUBLIC_KEY_PEM
    """
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    _require_pay_env("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY_PEM", "ALIPAY_PUBLIC_KEY_PEM")

    order = create_order(uid, "alipay", int(amount or 0), title=title)

    # TODO: 调用支付宝创建支付链接（网页支付/当面付等）
    return {
        "order_id": order["id"],
        "channel": "alipay",
        "status": order["status"],
        "amount": order["amount"],
        "pay_url": None,
        "message": "订单已创建（待接入支付宝下单接口）",
    }


@router.get("/api/billing/orders/{order_id}")
async def get_order_status(request: Request, order_id: str):
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    order = get_order(order_id)
    if not order or order.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {"order": order}


@router.post("/api/billing/mock/mark-paid/{order_id}")
async def mock_mark_paid(request: Request, order_id: str):
    """
    开发用：没有真实支付配置时，用于本地打通“升级 Pro”闭环。
    """
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    order = get_order(order_id)
    if not order or order.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="订单不存在")
    mark_order_paid(order_id, provider_trade_no="mock")
    # 简化：支付成功后给 30 天 Pro
    pro_until = int(time.time()) + 60 * 60 * 24 * 30
    set_subscription_plan(uid, "pro", pro_until=pro_until)
    return {"ok": True, "order_id": order_id, "plan": "pro", "pro_until": pro_until}


@router.post("/api/billing/wechatpay/notify")
async def wechatpay_notify(_: Request):
    """
    微信支付回调入口（骨架）。官方直连需要验签 + 解密回调报文。
    这里保留接口占位，避免部署路由缺失。
    """
    return JSONResponse({"ok": True})


@router.post("/api/billing/alipay/notify")
async def alipay_notify(_: Request):
    """
    支付宝异步通知入口（骨架）。官方直连需要验签。
    """
    return JSONResponse({"ok": True})

