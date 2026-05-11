"""知识库文档落盘：路径解析与安全段校验（不做分块与向量）。"""

import json
import re
from pathlib import Path
from typing import Any, Dict

# 后端根目录（含 data/）
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_KNOWLEDGE_DOCS_ROOT = _BACKEND_ROOT / "data" / "knowledge" / "documents"

# Windows 文件名非法字符及路径风险片段
_UNSAFE_SEGMENT = re.compile(r'[<>:"/\\|?*\x00]|\.\.')


def knowledge_documents_root() -> Path:
    """返回 knowledge documents 根目录路径。"""
    return _KNOWLEDGE_DOCS_ROOT


def assert_safe_segment(value: str, field_name: str) -> str:
    """
    校验 corpus_id / doc_id 等路径段：非空、无路径穿越与非法文件名字符。
    不通过时抛出 ValueError（由路由层转为 HTTP 400）。
    """
    s = str(value).strip()
    if not s:
        raise ValueError(f"{field_name} 不能为空")
    if _UNSAFE_SEGMENT.search(s):
        raise ValueError(
            f"{field_name} 含非法字符或路径片段（禁止 ..、斜杠、Windows 保留字符等）"
        )
    if s in (".", ".."):
        raise ValueError(f"{field_name} 非法")
    return s


def document_json_path(corpus_id: str, doc_id: str) -> Path:
    """返回单篇文档 JSON 的绝对路径。"""
    c = assert_safe_segment(corpus_id, "corpus_id")
    d = assert_safe_segment(doc_id, "doc_id")
    return _KNOWLEDGE_DOCS_ROOT / c / f"{d}.json"


def relative_document_path(corpus_id: str, doc_id: str) -> str:
    """相对 backend 根目录的 POSIX 风格路径字符串，便于响应与日志。"""
    p = document_json_path(corpus_id, doc_id)
    try:
        rel = p.relative_to(_BACKEND_ROOT)
    except ValueError:
        rel = p
    return rel.as_posix()


def save_document_json(
    corpus_id: str, doc_id: str, payload: Dict[str, Any], *, overwrite: bool
) -> Path:
    """
    将 payload 写入 JSON 文件。
    若文件已存在且 overwrite=False，抛出 FileExistsError。
    """
    path = document_json_path(corpus_id, doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(str(path))
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    return path


def load_document_json(corpus_id: str, doc_id: str) -> Dict[str, Any]:
    """读取已保存的文档 JSON；文件不存在则 FileNotFoundError。"""
    path = document_json_path(corpus_id, doc_id)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw)
