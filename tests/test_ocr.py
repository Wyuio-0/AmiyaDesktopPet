"""OCR module tests: backend availability and error paths (no network)."""
import pytest
from PIL import Image

from pet.ocr import OcrError, ocr_image, summarize_ai, winrt_available


@pytest.fixture()
def sample_image():
    return Image.new("RGB", (60, 40), (200, 200, 200))


class TestOcrBackends:
    def test_winrt_available_returns_bool(self):
        assert isinstance(winrt_available(), bool)

    def test_ocr_image_without_backends(self, sample_image):
        """无 winsdk 且无 api_key 时必须给出清晰错误。"""
        with pytest.raises(OcrError) as ei:
            ocr_image(sample_image, brain_cfg={})
        assert "winsdk" in str(ei.value)

    def test_ocr_image_no_cfg(self, sample_image):
        with pytest.raises(OcrError):
            ocr_image(sample_image, brain_cfg=None)

    def test_summarize_without_ai(self):
        with pytest.raises(OcrError) as ei:
            summarize_ai({}, "一些文字")
        assert "api_key" in str(ei.value)


@pytest.mark.skipif(not winrt_available(),
                    reason="winsdk 未安装，跳过离线 OCR 实测")
class TestWinrtIntegration:
    def test_ocr_winrt_returns_text(self, sample_image):
        from pet.ocr import _ocr_winrt
        assert isinstance(_ocr_winrt(sample_image), str)
