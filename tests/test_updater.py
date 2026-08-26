"""updater 版本比较测试（纯函数，不做网络请求）。"""
from pet.updater import is_newer


def test_is_newer():
    assert is_newer("v1.4.1", "1.4.0") is True
    assert is_newer("v1.4.0", "1.4.0") is False
    assert is_newer("v1.3.3", "1.4.0") is False
    assert is_newer("v2.0.0", "1.9.9") is True
    assert is_newer("v1.10.0", "1.9.0") is True    # 数字比较，不是字符串序
    assert is_newer("v1.4", "1.4.0") is False
    assert is_newer("", "1.4.0") is False
    assert is_newer("v1.4.0-rc1", "1.4.0") is False
