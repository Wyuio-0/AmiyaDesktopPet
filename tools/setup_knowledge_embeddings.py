"""可选：为讲义检索安装本地语义模型（sentence-transformers）。

用法：
    python tools/setup_knowledge_embeddings.py

会安装 sentence-transformers（连带 torch，约 2GB），首次检索时自动下载并
缓存多语言模型 paraphrase-multilingual-MiniLM-L12-v2（约 470MB）。

注意：只对**源码运行**（python main.py）生效——打包版 exe 不内置 torch，
讲义检索会自动回退到零依赖的词频（n-gram TF-IDF）后端。
"""

import subprocess
import sys


def main():
    print("==> 安装 sentence-transformers（含 torch，约 2GB，需要几分钟）…")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--upgrade",
         "sentence-transformers"])
    print("==> 安装完成。")
    print("    源码运行桌宠后，讲义检索将自动使用本地语义模型；")
    print("    未安装或打包版会静默回退到词频检索。")
    print("    可在 设置 → 通用 → 讲义检索 里关闭该后端。")


if __name__ == "__main__":
    main()
