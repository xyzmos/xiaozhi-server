from __future__ import annotations

from typing import Any

from app.schemas.common import JavaModel


class LoginRequest(JavaModel):
    # LoginController does not use @Valid; null/blank values reach its service logic.
    username: str | None = None
    password: str | None = None
    mobile_captcha: str | None = None
    captcha_id: str | None = None


class SmsVerificationRequest(JavaModel):
    # smsVerification likewise omits @Valid in the Java controller.
    phone: str | None = None
    captcha: str | None = None
    captcha_id: str | None = None


class PasswordChangeRequest(JavaModel):
    password: str | None = None
    new_password: str | None = None


class RetrievePasswordRequest(JavaModel):
    phone: str | None = None
    code: str | None = None
    password: str | None = None
    captcha_id: str | None = None


class TokenData(JavaModel):
    token: str
    expire: int
    client_hash: str | None


class UserDetailData(JavaModel):
    id: int
    username: str
    super_admin: int
    token: str
    status: int


class PublicConfigData(JavaModel):
    enable_mobile_register: bool
    version: str
    year: str
    allow_user_register: bool
    mobile_area_list: list[dict[str, Any]]
    beian_icp_num: str | None
    beian_ga_num: str | None
    name: str | None
    sm2_public_key: str
    system_web_menu: Any | None = None
