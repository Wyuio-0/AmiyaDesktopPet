"""Amiya persona + OpenAI-compatible chat client (stdlib urllib, no deps)."""

import json
import os
import urllib.request

from . import actions
from .settings import history_path

# Default Amiya persona (Arknights). Overridable via config.json "persona".
PERSONA = (
    "你是《明日方舟》中的阿米娅，罗德岛的公开领袖。你温柔、坚定、富有责任感，"
    "面对博士时既尊敬又亲近。你称呼对方为「博士」，自称「阿米娅」或「我」。"
    "你说话礼貌、真诚，偶尔流露少女的关心与坚强。回答简洁自然，一般一到三句话，"
    "像日常聊天，不要长篇大论，不要使用括号动作描写或表情符号，只用中文回答。"
    "当博士需要时，你可以调用提供的工具帮他操作电脑（打开程序、网页、搜索、"
    "调音量、控制媒体、锁屏、截图、报时、设置定时提醒），也能帮他查课表"
    "（query_schedule）、管理作业和考试（query_tasks / add_task）。"
    "做完后用一句自然的话告诉博士结果。"
    "重要：只要博士的要求能用工具完成——尤其是设置提醒/闹钟/番茄钟（set_reminder）、"
    "查课表、添加作业截止（add_task）、开程序、开网页这类操作——"
    "你必须实际调用对应的工具，绝不能只用嘴答应而不调用。"
    "先调用工具，再根据工具返回的结果回话。"
)

# Built-in replies used when no API key is configured (offline fallback).
FALLBACK = [
    "博士，您回来了。今天也辛苦了。",
    "有什么我能帮上忙的吗？罗德岛随时待命。",
    "请不要太勉强自己，博士。适当休息也很重要。",
    "只要博士还愿意前行，我就会一直陪在您身边。",
    "无论前路如何，我们都会一起面对的。",
]


def load_ai_config(char_dir):
    """Merge ai_config.json with env vars (env wins). Returns a dict."""
    cfg = {"base_url": "https://api.deepseek.com", "model": "deepseek-chat",
           "api_key": "", "temperature": 0.8, "allow_actions": True}
    path = os.path.join(char_dir, "ai_config.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    cfg["api_key"] = os.environ.get("PET_AI_KEY", cfg.get("api_key", ""))
    cfg["base_url"] = os.environ.get("PET_AI_BASE", cfg["base_url"])
    cfg["model"] = os.environ.get("PET_AI_MODEL", cfg["model"])
    return cfg


class AmiyaBrain:
    """Holds conversation state and produces replies."""

    def __init__(self, char_dir, persona=None, fallback=None, max_turns=8):
        self.cfg = load_ai_config(char_dir)
        self.persona = persona or PERSONA
        self.fallback = list(fallback or FALLBACK)
        self.max_turns = max_turns
        self.history_file = history_path(os.path.basename(char_dir))
        # Restore the last conversation so Amiya "remembers" across restarts.
        self.history = self._load_history()   # list of {"role","content"}
        self._fallback_i = 0
        self.knowledge = None   # pet.knowledge.KnowledgeBase（由窗口注入）

    def _knowledge_context(self):
        """按当前用户问题检索讲义片段，返回可注入 system 的上下文（或空串）。"""
        kb = self.knowledge
        if not kb:
            return ""
        question = ""
        for m in reversed(self.history):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                question = m["content"]
                break
        ctx = kb.context(question)
        if not ctx:
            return ""
        return ("\n\n以下是博士的课程资料片段（回答时请优先参考；"
                "若与问题无关可忽略）：\n" + ctx)

    @property
    def online(self):
        return bool(self.cfg.get("api_key"))

    def _load_history(self):
        """Load persisted history, keeping user/assistant/tool turns."""
        try:
            with open(self.history_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        turns = [c for c in (_clean_msg(m) for m in data) if c]
        return _trim_history(turns, self.max_turns)

    def _save_history(self):
        """Persist the bounded history; best-effort, never raises."""
        try:
            path = self.history_file
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            pass

    def clear_history(self):
        """Forget the conversation (memory + disk)."""
        self.history = []
        self._save_history()

    def reply(self, user_text):
        """Blocking call — run this off the UI thread."""
        self.history.append({"role": "user", "content": user_text})
        if not self.online:
            text = self._fallback_reply()
        else:
            try:
                text = self._call_llm()
            except Exception as e:  # network/auth/etc -> graceful message
                text = f"（连接出错了，博士稍后再试）{type(e).__name__}"
        self.history.append({"role": "assistant", "content": text})
        # keep only the last N turns to bound the context (cut at a safe
        # boundary so tool rounds aren't orphaned)
        self.history = _trim_history(self.history, self.max_turns)
        self._save_history()
        return text

    def reply_stream(self, user_text, on_delta=None):
        """Streaming variant of reply(): calls on_delta(accumulated_text) as
        content tokens arrive, and returns the final text. Off the UI thread.

        Offline (no key) has nothing to stream — the fallback line is delivered
        via a single on_delta call so the caller's code path stays uniform.
        """
        self.history.append({"role": "user", "content": user_text})
        if not self.online:
            text = self._fallback_reply()
            if on_delta:
                on_delta(text)
        else:
            try:
                text = self._call_llm_stream(on_delta)
            except Exception as e:
                text = f"（连接出错了，博士稍后再试）{type(e).__name__}"
                if on_delta:
                    on_delta(text)
        self.history.append({"role": "assistant", "content": text})
        self.history = _trim_history(self.history, self.max_turns)
        self._save_history()
        return text

    def _fallback_reply(self):
        text = self.fallback[self._fallback_i % len(self.fallback)]
        self._fallback_i += 1
        return text

    def _call_llm(self):
        """Chat with an optional tool-call loop (max 4 tool rounds)."""
        use_tools = self.cfg.get("allow_actions", True)
        system = {"role": "system",
                  "content": self.persona + self._knowledge_context()}
        msgs = [system] + list(self.history)
        for _ in range(4):
            msg = self._post(msgs, use_tools)
            calls = msg.get("tool_calls")
            if not calls:
                return (msg.get("content") or "").strip()
            # Record the tool round in both the working list AND the persisted
            # history, so future turns replay Amiya *actually calling* the tool
            # rather than just her final sentence (see _clean_msg).
            self._record_tool_round(msgs, msg, calls)
        # Too many rounds; return whatever text we have.
        return (msgs[-1].get("content") or "好的，博士。").strip()

    def _post(self, msgs, use_tools):
        payload = {"model": self.cfg["model"], "messages": msgs,
                   "temperature": self.cfg.get("temperature", 0.8),
                   "stream": False}
        if use_tools:
            payload["tools"] = actions.TOOLS
        body = json.dumps(payload).encode("utf-8")
        url = self.cfg["base_url"].rstrip("/") + "/v1/chat/completions"
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.cfg["api_key"],
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]

    def _call_llm_stream(self, on_delta):
        """Streaming chat with an optional tool-call loop (max 4 rounds).

        Tool-call rounds don't stream visible text; the final answer round
        streams its content tokens out through on_delta as they arrive.
        """
        use_tools = self.cfg.get("allow_actions", True)
        system = {"role": "system",
                  "content": self.persona + self._knowledge_context()}
        msgs = [system] + list(self.history)
        for _ in range(4):
            msg = self._post_stream(msgs, use_tools, on_delta)
            calls = msg.get("tool_calls")
            if not calls:
                return (msg.get("content") or "").strip()
            self._record_tool_round(msgs, msg, calls)
        return (msgs[-1].get("content") or "好的，博士。").strip()

    def _record_tool_round(self, msgs, assistant_msg, calls):
        """Run each requested tool and append the assistant tool-call turn plus
        its tool results to both the working `msgs` and the persisted history.
        """
        # The assistant turn that requested the tools (keep only the fields the
        # API needs when replaying — role/content/tool_calls).
        tc = {"role": "assistant",
              "content": assistant_msg.get("content") or "",
              "tool_calls": calls}
        msgs.append(tc)
        self.history.append(tc)
        for call in calls:
            fn = call["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            result = actions.run_action(fn["name"], args)
            tool_msg = {"role": "tool", "tool_call_id": call["id"],
                        "content": result}
            msgs.append(tool_msg)
            self.history.append(tool_msg)

    def _post_stream(self, msgs, use_tools, on_delta):
        payload = {"model": self.cfg["model"], "messages": msgs,
                   "temperature": self.cfg.get("temperature", 0.8),
                   "stream": True}
        if use_tools:
            payload["tools"] = actions.TOOLS
        body = json.dumps(payload).encode("utf-8")
        url = self.cfg["base_url"].rstrip("/") + "/v1/chat/completions"
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.cfg["api_key"],
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            return _consume_stream(resp, on_delta)


def _trim_history(turns, max_turns):
    """Bound history to ~max_turns exchanges, cutting only at a `user` message.

    A `tool` message is only valid right after the assistant `tool_calls` that
    produced it, and an assistant `tool_calls` turn must be followed by its tool
    results. Slicing blindly could orphan either and make the API reject the
    request, so we trim to a safe boundary: the first `user` message at/after
    the naive cut point (falling back to keeping more rather than breaking a
    round).
    """
    limit = 2 * max_turns
    if len(turns) <= limit:
        return turns
    start = len(turns) - limit
    while start < len(turns) and turns[start].get("role") != "user":
        start += 1
    if start >= len(turns):  # no clean boundary found; keep from first user
        start = next((i for i, m in enumerate(turns)
                      if m.get("role") == "user"), 0)
    return turns[start:]


def _clean_msg(m):
    """Normalise one history message to the minimal fields we persist/replay.

    Keeps user/assistant/tool turns — crucially including assistant `tool_calls`
    and their `tool` results — so the replayed context shows Amiya *actually
    using* the tools. Storing only the final text taught the model that
    promising ("好的，15秒后提醒您") without a tool call was acceptable, so it
    stopped calling set_reminder after a few turns. Returns None if unusable.
    """
    if not isinstance(m, dict):
        return None
    role = m.get("role")
    if role == "user":
        c = m.get("content")
        return {"role": "user", "content": c} if isinstance(c, str) else None
    if role == "assistant":
        out = {"role": "assistant", "content": m.get("content") or ""}
        calls = m.get("tool_calls")
        if isinstance(calls, list) and calls:
            out["tool_calls"] = calls
        return out
    if role == "tool":
        if m.get("tool_call_id") and isinstance(m.get("content"), str):
            return {"role": "tool", "tool_call_id": m["tool_call_id"],
                    "content": m["content"]}
    return None


def _accum_tool_call(store, delta):
    """Merge a streamed tool_call delta into `store` (keyed by index)."""
    idx = delta.get("index", 0)
    slot = store.setdefault(idx, {"id": "", "type": "function",
                                  "function": {"name": "", "arguments": ""}})
    if delta.get("id"):
        slot["id"] = delta["id"]
    fn = delta.get("function") or {}
    if fn.get("name"):
        slot["function"]["name"] += fn["name"]
    if fn.get("arguments"):
        slot["function"]["arguments"] += fn["arguments"]


def _consume_stream(lines, on_delta):
    """Parse an OpenAI-compatible SSE stream into a single message dict.

    `lines` is any iterable of raw bytes/str lines (an http response works, and
    so does a list — which makes this unit-testable without a network). Content
    tokens are pushed to on_delta(accumulated_text) as they arrive.
    """
    content = ""
    tool_store = {}
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        choices = chunk.get("choices") or [{}]
        delta = choices[0].get("delta") or {}
        if delta.get("content"):
            content += delta["content"]
            if on_delta:
                on_delta(content)
        for tc in delta.get("tool_calls") or []:
            _accum_tool_call(tool_store, tc)
    msg = {"role": "assistant", "content": content}
    if tool_store:
        msg["tool_calls"] = [tool_store[k] for k in sorted(tool_store)]
    return msg
