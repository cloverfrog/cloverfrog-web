"""Configuration independent of the working directory and checkout name."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


# 统一读取运行配置；固定 .env 所在位置，避免从不同目录启动时读到另一份配置。
@dataclass(frozen=True)
class Settings:
    pocketbase_url: str = 'https://pocketbase.cloverfrog.xyz'
    public_origin: str = 'https://cloverfrog.xyz'
    dev_mode: bool = False
    alist_url: str = 'https://alist.cloverfrog.xyz'
    alist_root: str = ''
    alist_token: str = field(default='', repr=False)

    @classmethod
    def load(cls):
        # 部署环境变量优先于本地 .env；frozen 配置供所有请求共享，运行中不修改。
        load_dotenv(ROOT / '.env', override=False)
        settings = cls(
            pocketbase_url=os.getenv('POCKETBASE_URL', cls.pocketbase_url).rstrip('/'),
            public_origin=os.getenv('PUBLIC_ORIGIN', cls.public_origin).rstrip('/'),
            dev_mode=os.getenv('DEV_MODE', 'false').lower() == 'true',
            alist_url=os.getenv('ALIST_URL', cls.alist_url).rstrip('/'),
            alist_root=os.getenv('ALIST_ROOT', cls.alist_root).rstrip('/'),
            alist_token=os.getenv('ALIST_TOKEN', ''),
        )
        # Origin 校验要求精确匹配，因此配置必须是纯来源地址，不能附带路径。
        origin = urlsplit(settings.public_origin)
        if (
            origin.scheme not in ('http', 'https')
            or not origin.netloc
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ValueError('PUBLIC_ORIGIN must be an origin without a path')
        if not settings.dev_mode and origin.scheme != 'https':
            raise ValueError('Production PUBLIC_ORIGIN must use HTTPS')
        return settings
