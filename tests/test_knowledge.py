"""Knowledge base tests: chunking, retrieval, context injection."""
import pytest

from pet.knowledge import KnowledgeBase, _segment, _tokenize


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class TestKnowledgeBase:
    def test_load_and_retrieve(self, tmp_path):
        _write(tmp_path, "笔记.txt",
               "二叉树是一种数据结构。\n\n树的遍历有三种：先序、中序、后序。\n\n"
               "排序算法有快速排序。")
        kb = KnowledgeBase(folder=str(tmp_path))
        assert len(kb) == 3
        hits = kb.retrieve("树的遍历", top_k=1)
        assert hits and "遍历" in hits[0]["text"]
        assert hits[0]["source"] == "笔记.txt"

    def test_empty_folder(self, tmp_path):
        kb = KnowledgeBase(folder=str(tmp_path))
        assert len(kb) == 0 and not kb

    def test_context_marks_source(self, tmp_path):
        _write(tmp_path, "a.md", "线性代数：矩阵乘法。")
        kb = KnowledgeBase(folder=str(tmp_path))
        ctx = kb.context("矩阵乘法")
        assert "【a.md】" in ctx and "矩阵乘法" in ctx

    def test_context_empty_when_no_match(self, tmp_path):
        _write(tmp_path, "a.md", "线性代数：矩阵乘法。")
        kb = KnowledgeBase(folder=str(tmp_path))
        assert kb.context("量子力学") == ""

    def test_reload_picks_up_new_files(self, tmp_path):
        kb = KnowledgeBase(folder=str(tmp_path))
        assert len(kb) == 0
        _write(tmp_path, "x.txt", "操作系统：进程调度。")
        kb.reload()
        assert len(kb) == 1

    def test_long_paragraph_segmented(self, tmp_path):
        long_text = "第一句。" * 200   # > max_len(500)
        _write(tmp_path, "long.txt", long_text)
        kb = KnowledgeBase(folder=str(tmp_path))
        assert len(kb) >= 2


class TestHelpers:
    def test_tokenize_cjk_and_english(self):
        toks = _tokenize("Binary tree 二叉树")
        assert "binary" in toks and "tree" in toks and "二" in toks

    def test_tokenize_bigrams(self):
        toks = _tokenize("傅里叶变换")
        assert "傅里" in toks and "里叶" in toks and "变换" in toks

    def test_segment_splits_paragraphs(self):
        chunks = _segment("第一段。\n\n第二段。")
        assert len(chunks) == 2


class TestTfidfRetrieval:
    def test_bigram_beats_unrelated(self, tmp_path):
        """n-gram TF-IDF：主题相关的片段应排在最前。"""
        _write(tmp_path, "a.txt",
               "傅里叶变换把时域信号变换到频域分析。\n\n"
               "快速傅里叶变换 FFT 是数字信号处理的基石。\n\n"
               "今天天气很好适合去操场跑步。")
        kb = KnowledgeBase(folder=str(tmp_path), use_embed=False)
        hits = kb.retrieve("FFT 快速傅里叶", top_k=1)
        assert hits and "FFT" in hits[0]["text"]

    def test_query_terms_absent_return_empty(self, tmp_path):
        _write(tmp_path, "a.md", "线性代数：矩阵乘法。")
        kb = KnowledgeBase(folder=str(tmp_path), use_embed=False)
        assert kb.retrieve("量子力学纠缠") == []

    def test_embed_unavailable_falls_back(self, tmp_path):
        """没有 sentence-transformers 时 use_embed=True 也正常走词频。"""
        _write(tmp_path, "n.txt", "操作系统：进程调度与死锁。")
        kb = KnowledgeBase(folder=str(tmp_path), use_embed=True)
        assert kb._emb_matrix is None          # 未安装 -> 无向量矩阵
        hits = kb.retrieve("进程调度", top_k=1)
        assert hits and "调度" in hits[0]["text"]
