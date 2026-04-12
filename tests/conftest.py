import os
import tempfile

import pytest

# 必须在首次 import backend.* 之前设置，保证 main.init_db 落到独立文件
_pytest_db_dir = tempfile.mkdtemp(prefix="aimovie_pytest_")
os.environ["DATABASE_PATH"] = os.path.join(_pytest_db_dir, "app.db")
os.environ["AUTH_SECRET_KEY"] = "pytest-secret-key"
# 测试里需断言解析/下载额度；与本地开发默认「不限制」区分开
os.environ["DEV_BYPASS_EXTRACT_DOWNLOAD"] = "0"

from backend.database import init_db  # noqa: E402

init_db()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from backend.main import app

    return TestClient(app)
