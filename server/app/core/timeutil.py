"""统一的时区时间工具。

历史问题：后端时间获取混用了三种约定（Python 侧 datetime.utcnow、SQLite 的
func.now()/CURRENT_TIMESTAMP、以及个别 datetime.now() 本地时间），导致存入数据库
的是 UTC，前端原样显示后比中国本地时间慢 8 小时。

修复原则：统一使用「显式东八区」本地时间，不依赖部署机器的 TZ 设置
（Docker 容器默认可能是 UTC，datetime.now() 在容器里会算错）。
"""
from datetime import datetime, timedelta, timezone

# 中国标准时间（东八区）。显式写死，部署到任何环境结果一致。
CN_TZ = timezone(timedelta(hours=8))
UTC_TZ = timezone.utc


def now_local() -> datetime:
    """东八区本地时间（naive datetime），不依赖部署环境的 TZ 设置。

    用于所有「面向用户展示 / 与本地语义一致」的时间字段（created_at、
    updated_at、各类业务时间等）。
    """
    return datetime.now(CN_TZ).replace(tzinfo=None)


def now_utc() -> datetime:
    """显式 UTC 时间（naive datetime）。

    仅用于**必须按 UTC 语义**的场景，例如 JWT 的 exp 过期时间。
    不要把它用于用户可见的文档时间字段。
    """
    return datetime.now(UTC_TZ).replace(tzinfo=None)
