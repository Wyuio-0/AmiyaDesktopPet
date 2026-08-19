"""OCR：从截图中提取文字（供截图翻译/截图总结使用）。

后端优先级：
  1. **Windows 自带 OCR**（WinRT，通过可选的 winsdk 包）——离线、免费、
     中文支持好。安装：`pip install winsdk`。未安装则跳过。
  2. **AI 视觉模型**（OpenAI 兼容 /chat/completions，image_url base64）——
     需要 ai_config 里配置支持视觉的模型（如 moonshot-v1-8k-vision-preview）。
两个后端都不可用时抛 OcrError，由调用方给出安装提示。

翻译与总结的 AI 调用是**无状态**的（不进对话历史）。
"""

import base64
import io
import json
import urllib.request

# winsdk 是可选依赖：没有就降级到 AI 视觉 / 报错提示。
try:
    import winsdk.windows.graphics.imaging as _wimg
    import winsdk.windows.media.ocr as _wocr
    import winsdk.windows.storage.streams as _wstreams
    import winsdk.windows.globalization as _wglob
    _WINRT_OK = True
except Exception:
    _wimg = _wocr = _wstreams = _wglob = None
    _WINRT_OK = False


class OcrError(Exception):
    pass


def winrt_available():
    """Windows 自带 OCR 是否可用（winsdk 已安装）。"""
    return _WINRT_OK


def _ocr_winrt(image):
    """PIL Image -> 文字（Windows 自带 OCR，需 winsdk）。"""
    import asyncio

    async def go():
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        stream = _wstreams.InMemoryRandomAccessStream()
        writer = _wstreams.DataWriter(stream)
        writer.write_bytes(buf.getvalue())
        await writer.store_async()
        stream.seek(0)
        decoder = await _wimg.BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = _wocr.OcrEngine.try_create_from_language(
            _wglob.Language("zh-CN"))
        if engine is None:
            engine = _wocr.OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return ""
        result = await engine.recognize_async(bitmap)
        return "\n".join(line.text for line in result.lines)

    return asyncio.run(go())


def _ocr_via_ai(image, cfg):
    """把图片发给 AI 视觉模型识别文字。"""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    data_url = "data:image/png;base64," + b64
    payload = {
        "model": cfg.get("model", "moonshot-v1-8k-vision-preview"),
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": "请识别这张截图中的全部文字，原样输出，"
                         "不要添加任何解释、注释或额外文字。"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        "temperature": 0,
    }
    url = str(cfg["base_url"]).rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"].get("content", "").strip()


def ocr_image(image, brain_cfg=None):
    """识别 PIL Image 中的文字，返回 (text, backend)。backend ∈ {'winrt','ai'}。"""
    if _WINRT_OK:
        try:
            text = _ocr_winrt(image).strip()
            if text:
                return text, "winrt"
        except Exception:
            pass  # 降级到 AI
    if brain_cfg and brain_cfg.get("api_key"):
        try:
            return _ocr_via_ai(image, brain_cfg), "ai"
        except Exception as e:
            raise OcrError("AI 视觉识别失败：%s" % type(e).__name__)
    raise OcrError(
        "OCR 不可用：请先 pip install winsdk 使用离线识别，"
        "或在 ai_config.json 配置支持视觉的模型（如 moonshot-v1-8k-vision-preview）。")


def summarize_ai(cfg, text, target_lang="中文"):
    """用 AI 总结 OCR 出的文字（无状态调用）。返回总结或抛 OcrError。"""
    if not (cfg and cfg.get("api_key")):
        raise OcrError("总结需要配置 AI：请在 ai_config.json 填写 api_key。")
    prompt = ("你是学习助手。请用%s总结以下文字（来自截图），"
              "提炼要点、条理清晰，不要超过 200 字：\n\n%s"
              % (target_lang, text[:6000]))
    payload = {
        "model": cfg.get("model"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    url = str(cfg["base_url"]).rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"].get("content", "").strip()
    except Exception as e:
        raise OcrError("AI 总结失败：%s" % type(e).__name__)
