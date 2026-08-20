"""讲义/笔记知识库：轻量切块 + 关键词检索（无外部依赖）。

把 `%APPDATA%\\AmiyaPet\\knowledge\\` 下的 `.txt` / `.md` 讲义切块建索引，
对话时按当前问题检索最相关的片段注入给大模型，让阿米娅基于课件答疑。

检索是朴素的词频打分（中文按单字、英文按词），不引入向量库：
对这个体量的学生讲义足够用，且零依赖、离线可用。
"""

import os
import re

from .settings import config_dir


class KnowledgeBase:
    """加载讲义并支持按问题检索相关片段。"""

    def __init__(self, folder=None):
        self.folder = folder or os.path.join(config_dir(), "knowledge")
        self.chunks = []            # [{"text", "source"}]
        self.reload()

    def reload(self):
        """重新扫描知识库目录（用户放入新讲义后调用）。"""
        self.chunks = []
        if not os.path.isdir(self.folder):
            return
        for fn in sorted(os.listdir(self.folder)):
            if not fn.lower().endswith((".txt", ".md")):
                continue
            path = os.path.join(self.folder, fn)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            for chunk in _segment(text):
                chunk = chunk.strip()
                if chunk:
                    self.chunks.append({"text": chunk, "source": fn})

    def __bool__(self):
        return bool(self.chunks)

    def __len__(self):
        return len(self.chunks)

    def retrieve(self, query, top_k=3):
        """返回与 query 最相关的 top_k 个片段（按词频打分降序）。"""
        if not self.chunks or not query:
            return []
        qwords = _tokenize(query)
        if not qwords:
            return []
        scored = []
        for ch in self.chunks:
            text = ch["text"]
            score = sum(text.count(w) for w in qwords) / max(len(text), 1)
            if score > 0:
                scored.append((score, ch))
        scored.sort(key=lambda x: -x[0])
        return [ch for _, ch in scored[:top_k]]

    def context(self, query, max_chars=1500):
        """把检索结果拼成可注入 prompt 的上下文文本（带来源标注）。"""
        parts = []
        total = 0
        for ch in self.retrieve(query):
            piece = "【%s】\n%s" % (ch["source"], ch["text"])
            if total + len(piece) > max_chars:
                piece = piece[:max_chars - total]
            parts.append(piece)
            total += len(piece)
            if total >= max_chars:
                break
        return "\n\n".join(parts) if parts else ""


def _tokenize(text):
    """粗分词：英文/数字按连续词，中文按单字（朴素但对检索够用）。"""
    words = re.findall(r"[a-zA-Z0-9_]{2,}", text.lower())
    words += re.findall(r"[\u4e00-\u9fff]", text)
    return words


def _segment(text, max_len=500):
    """按段落切块；超长段落再按句子（。！？；）切到 ≤ max_len。"""
    chunks = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_len:
            chunks.append(para)
            continue
        buf = ""
        for sent in re.split(r"(?<=[。！？；;])", para):
            if len(buf) + len(sent) > max_len and buf:
                chunks.append(buf)
                buf = sent
            else:
                buf += sent
        if buf:
            chunks.append(buf)
    return chunks
