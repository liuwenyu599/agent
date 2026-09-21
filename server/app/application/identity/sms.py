"""短信通道预留（政务内网）。

当前**不接入任何公网短信服务**。后续政务内网短信网关就绪后，只需实现
SmsProvider 协议并在依赖注入处替换 NullSmsProvider 即可，业务代码不动。
"""
from typing import Optional, Protocol


class SmsProvider(Protocol):
    """短信发送能力协议。"""

    def send_code(self, mobile: str, code: str, scene: str = "verify") -> bool:
        """发送验证码。

        :param mobile: 目标手机号（政务内网白名单号码）
        :param code:   验证码明文
        :param scene:  业务场景，如 reset_password / login
        :return: 是否发送成功
        """
        ...


class NullSmsProvider:
    """默认实现：不发送任何短信（政务内网短信未接入）。"""

    def send_code(self, mobile: str, code: str, scene: str = "verify") -> bool:
        raise NotImplementedError("政务内网短信通道尚未接入，暂不支持短信验证码")


def get_sms_provider() -> SmsProvider:
    """获取短信通道实现（当前恒为未接入的空实现）。"""
    return NullSmsProvider()


__all__ = ["SmsProvider", "NullSmsProvider", "get_sms_provider"]


def _mask_mobile(mobile: Optional[str]) -> str:
    """手机号脱敏，供日志使用（日志严禁出现完整号码与任何密码）。"""
    if not mobile:
        return ""
    return f"{mobile[:3]}****{mobile[-4:]}" if len(mobile) >= 7 else "***"
