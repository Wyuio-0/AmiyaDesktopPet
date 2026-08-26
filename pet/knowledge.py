"""讲义/笔记知识库：切块 + 检索（默认零依赖，可选本地语义模型）。

把 `%APPDATA%\\AmiyaPet\\knowledge\\` 下的 `.txt` / `.md` 讲义切块建索引，
对话时按当前问题检索最相关的片段注入给大模型，让阿米娅基于课件答疑。

检索后端（KnowledgeBase(use_embed=...) 控制）：
1. **词频升级版（默认，零依赖）**：n-gram（中文单字+双字、英文词）TF-IDF +
   余弦相似度排序——比朴素的单字词频打分更准，依然离线、无依赖。
2. **本地语义检索（可选）**：检测到 `sentence-transformers`（含 torch）时自动
   使用多语言 embedding 模型做语义匹配；未安装则静默回退后端 1。
   安装：`python tools/setup_knowledge_embeddings.py`。
   注意：打包版 exe 不内置 torch（导入被守卫，PyInstaller 不会打包），
   语义检索只对**源码运行**（python main.py）生效。

embedding 的导入用运行时拼接的模块名（importlib.import_module("sentence_"
"transformers")），避免 PyInstaller 静态分析把它打进 exe。
"""

import importlib
import math
import os
import re

from . import logging as petlog
from .settings import config_dir

# 多语言 embedding 模型（中英皆可；约 470MB，首次使用时下载并缓存）。
_EMBED_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

_MODEL = None            # 缓存的 SentenceTransformer 实例


def _embed_available():
    """sentence-transformers + torch 是否可导入（守卫式，exe 里恒为 False）。"""
    try:
        importlib.import_module("sentence_" + "transformers")
        importlib.import_module("torch")
        return True
    except Exception:
        return False


def _embed_model():
    global _MODEL
    if _MODEL is None:
        st = importlib.import_module("sentence_" + "transformers")
        _MODEL = st.SentenceTransformer(_EMBED_MODEL_NAME)
    return _MODEL


def _encode_texts(texts):
    import numpy as np
    model = _embed_model()
    vecs = model.encode(texts, convert_to_numpy=True,
                        normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def _encode_query(query):
    return _encode_texts([query])[0]


class KnowledgeBase:
    """加载讲义并支持按问题检索相关片段。"""

    def __init__(self, folder=None, use_embed=True):
        self.folder = folder or os.path.join(config_dir(), "knowledge")
        self.use_embed = bool(use_embed)
        self.chunks = []            # [{"text", "source"}]
        self._docs = []             # 每块的 token 列表（TF-IDF 用）
        self._idf = {}
        self._doc_weights = []      # [(token->tfidf 权重 dict, 模长)]
        self._emb_matrix = None     # (N, D) 归一化向量；embedding 可用时非空
        self.reload()

    def reload(self):
        """重新扫描知识库目录（用户放入新讲义后调用）。"""
        self.chunks = []
        if not os.path.isdir(self.folder):
            self._build_index()
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
        self._build_index()

    def _build_index(self):
        """重建 TF-IDF 索引；embedding 可用时额外编码向量矩阵。"""
        self._docs = [_tokenize(c["text"]) for c in self.chunks]
        n = len(self._docs)
        df = {}
        for toks in self._docs:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1
                     for t, c in df.items()}
        self._doc_weights = []
        for toks in self._docs:
            tf = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            w = {t: (1 + math.log(tf[t])) * self._idf[t] for t in tf}
            norm = math.sqrt(sum(v * v for v in w.values())) or 1.0
            self._doc_weights.append((w, norm))

        self._emb_matrix = None
        if self.use_embed and n and _embed_available():
            try:
                self._emb_matrix = _encode_texts([c["text"] for c in self.chunks])
                petlog.log("knowledge: 本地语义检索已启用（%d 片段）" % n)
            except Exception:
                self._emb_matrix = None
                petlog.log("knowledge: 语义模型加载失败，回退词频检索")

    def __bool__(self):
        return bool(self.chunks)

    def __len__(self):
        return len(self.chunks)

    def retrieve(self, query, top_k=3):
        """返回与 query 最相关的 top_k 个片段（语义 > TF-IDF > 空）。"""
        if not self.chunks or not query:
            return []
        if self._emb_matrix is not None:
            try:
                import numpy as np
                qv = _encode_query(query)
                sims = self._emb_matrix @ qv      # (N,) 余弦（已归一化）
                order = np.argsort(-sims)[:top_k]
                return [self.chunks[i] for i in order
                        if float(sims[i]) > 0]
            except Exception:
                pass    # 语义检索失败回退 TF-IDF
        return _retrieve_tfidf(query, self._idf,
                               self._doc_weights, self.chunks, top_k)

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
    """粗分词：英文/数字按连续词，中文按单字 + 相邻双字（bigram）。"""
    words = re.findall(r"[a-zA-Z0-9_]{2,}", text.lower())
    han = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = [a + b for a, b in zip(han, han[1:])]
    return words + han + bigrams


def _retrieve_tfidf(query, idf, doc_weights, chunks, top_k):
    """n-gram TF-IDF 余弦检索（零依赖后端）。"""
    qtoks = _tokenize(query)
    if not qtoks:
        return []
    qtf = {}
    for t in qtoks:
        qtf[t] = qtf.get(t, 0) + 1
    qvec = {t: (1 + math.log(qtf[t])) * idf.get(t, 0.0)
            for t in qtf if idf.get(t, 0.0) > 0}
    if not qvec:
        return []
    qn = math.sqrt(sum(v * v for v in qvec.values())) or 1.0
    scored = []
    for (w, norm), ch in zip(doc_weights, chunks):
        s = sum(w.get(t, 0.0) * v for t, v in qvec.items())
        if s > 0:
            scored.append((s / (norm * qn), ch))
    scored.sort(key=lambda x: -x[0])
    return [ch for _, ch in scored[:top_k]]


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
