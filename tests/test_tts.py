"""tts 手动启动服务参与空闲自动停止的开关测试（不打网络、不杀真实服务）。"""
from pet import tts


def test_manual_auto_stop_flag():
    tts.set_manual_auto_stop(True)
    assert tts._manual_auto_stop is True
    tts.set_manual_auto_stop(False)
    assert tts._manual_auto_stop is False


def test_manual_flag_gate(monkeypatch):
    """默认保护手动服务；勾选后越过保护进入空闲判断（可观测：last_used 被清零）。"""
    monkeypatch.setattr(tts, "clone_ready", lambda timeout=0.3: False)
    tts._manual_start = True
    try:
        # 默认（False）：手动启动被保护，_clone_last_used 原样保留
        tts.set_manual_auto_stop(False)
        tts._clone_last_used = 12345.0
        tts.maybe_stop_idle_clone(600)
        assert tts._clone_last_used == 12345.0

        # 勾选后（True）：越过保护，服务未跑 -> 清零并返回 False
        tts.set_manual_auto_stop(True)
        tts._clone_last_used = 12345.0
        assert tts.maybe_stop_idle_clone(600) is False
        assert tts._clone_last_used == 0.0
    finally:
        tts._manual_start = False
        tts._clone_last_used = 0.0
        tts.set_manual_auto_stop(False)
