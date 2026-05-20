"""知识库 RAG：基于 LangChain + FAISS 的检索与 stuff 问答链。"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from .retrieval_fusion import (
    BM25CorpusIndex,
    FusionHit,
    apply_rerank_to_hits,
    fuse_vector_bm25,
    hybrid_alpha,
    hybrid_enabled,
    retrieve_initial_k,
    rerank_enabled,
)

logger = logging.getLogger(__name__)

# 与 manifest 对齐：变更分块/检索栈时需递增
MANIFEST_VERSION = 2
RETRIEVAL_STACK_VERSION = 2
DOC2QUERY_VERSION = 1
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 180
CHUNK_SEPARATORS: List[str] = ["\n## ", "\n### ", "\n\n", "\n", "。", ".", " ", ""]

KNOWLEDGE_QA_SYSTEM_PROMPT = """你是技术面试 Tutor。请严格基于提供的知识库片段回答，不要编造未在片段中出现的事实。

要求：
1. 回答语言遵循 answer_language（zh/en/mixed）。
2. mixed 模式：先中文结论，再给简短 English 补充。
3. 如果上下文不足，请明确说明信息不足，并给出可继续追问的方向。
4. 回答用 Markdown，结构清晰，尽量简洁。
"""

_KNOWLEDGE_STUFF_HUMAN = (
    "answer_language={answer_language}\n\n"
    "用户问题：{input}\n\n"
    "知识库片段：\n{context}\n\n"
    "请严格基于上述片段回答。"
)


@dataclass
class ScoredChunk:
    """知识库检索命中及分数字段。"""

    document: Document
    score: float
    fusion_score: float = 0.0
    vector_score: float = 0.0
    bm25_score: float = 0.0
    rerank_score: Optional[float] = None


def _knowledge_qa_stuff_prompt_template() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", KNOWLEDGE_QA_SYSTEM_PROMPT),
            ("human", _KNOWLEDGE_STUFF_HUMAN),
        ]
    )


def _chunk_embed_text(ch: Document) -> str:
    """分块嵌入文本：Title + 正文 + 可选 synthetic_queries。"""
    md = ch.metadata or {}
    t = str(md.get("title") or "").strip()
    body = str(ch.page_content or "").strip()
    parts: List[str] = []
    if t:
        parts.append(f"Title: {t}\n\n{body}")
    else:
        parts.append(body)
    syn = md.get("synthetic_queries") or []
    if isinstance(syn, list) and syn:
        qs = [str(q).strip() for q in syn if str(q).strip()]
        if qs:
            parts.append("Q: " + " | ".join(qs))
    return "\n".join(parts)


class KnowledgeRAGService:
    """统一知识库索引与检索服务（单库，不拆中英文）。"""

    def __init__(
        self,
        *,
        docs_root: Path,
        embedding_model: str = "text-embedding-3-small",
        chat_model: str = "gpt-4o-mini",
    ) -> None:
        self._docs_root = docs_root
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._ready = False
        self._vectorstore: FAISS | None = None
        self._chunks: List[Document] = []
        self._bm25 = BM25CorpusIndex()
        self._doc_count = 0
        self._index_source: str = "none"

    @property
    def ready(self) -> bool:
        return self._ready and self._vectorstore is not None

    @property
    def doc_count(self) -> int:
        return self._doc_count

    @property
    def index_source(self) -> str:
        return self._index_source

    @property
    def bm25_ready(self) -> bool:
        return self._bm25.ready

    def _faiss_store_dir(self) -> Path:
        raw = str(os.getenv("KNOWLEDGE_FAISS_PATH") or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
        return (self._docs_root.parent / "faiss_index").resolve()

    def _manifest_path(self) -> Path:
        return self._faiss_store_dir() / "manifest.json"

    @staticmethod
    def _splitter() -> RecursiveCharacterTextSplitter:
        return RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=CHUNK_SEPARATORS,
        )

    def _documents_fingerprint(self) -> str:
        h = hashlib.sha256()
        if not self._docs_root.exists():
            return hashlib.sha256(b"").hexdigest()
        for p in sorted(self._docs_root.rglob("*.json")):
            try:
                rel = p.relative_to(self._docs_root)
                st = p.stat()
                h.update(str(rel).encode("utf-8"))
                h.update(b"\0")
                h.update(str(st.st_mtime_ns).encode("ascii"))
                h.update(b"\0")
                h.update(str(st.st_size).encode("ascii"))
                h.update(b"\n")
            except OSError:
                continue
        return h.hexdigest()

    def _expected_manifest(self, *, docs_fingerprint: str) -> Dict[str, Any]:
        return {
            "manifest_version": MANIFEST_VERSION,
            "retrieval_stack_version": RETRIEVAL_STACK_VERSION,
            "doc2query_version": DOC2QUERY_VERSION,
            "embedding_model": self._embedding_model,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "separators": CHUNK_SEPARATORS,
            "docs_fingerprint": docs_fingerprint,
        }

    def _manifest_matches(self, data: Dict[str, Any], *, docs_fingerprint: str) -> bool:
        try:
            exp = self._expected_manifest(docs_fingerprint=docs_fingerprint)
            for k, v in exp.items():
                if data.get(k) != v:
                    return False
            return True
        except Exception:
            return False

    @staticmethod
    def hit_snippet(page_content: str, max_len: int = 220) -> str:
        raw = str(page_content or "").strip()
        if raw.startswith("Title:"):
            sep = raw.find("\n\n")
            if sep != -1:
                raw = raw[sep + 2 :].strip()
        s = " ".join(raw.split())
        if len(s) <= max_len:
            return s
        return s[:max_len] + "…"

    def _load_documents(self) -> List[Document]:
        if not self._docs_root.exists():
            return []
        docs: List[Document] = []
        for p in sorted(self._docs_root.rglob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            body = str(data.get("body") or "").strip()
            if not body:
                continue
            corpus_id = str(data.get("corpus_id") or p.parent.name).strip()
            doc_id = str(data.get("doc_id") or p.stem).strip()
            title = str(data.get("title") or doc_id).strip()
            lang = str(data.get("lang") or "").strip().lower()
            topic_slugs = data.get("topic_slugs") or []
            if not isinstance(topic_slugs, list):
                topic_slugs = []
            syn = data.get("synthetic_queries") or []
            if not isinstance(syn, list):
                syn = []
            source = data.get("source") or {}
            source_url = str(source.get("url") or "").strip() if isinstance(source, dict) else ""
            docs.append(
                Document(
                    page_content=body,
                    metadata={
                        "corpus_id": corpus_id,
                        "doc_id": doc_id,
                        "title": title,
                        "lang": lang,
                        "topic_slugs": [str(x) for x in topic_slugs],
                        "source_url": source_url,
                        "synthetic_queries": [str(x) for x in syn if str(x).strip()],
                    },
                )
            )
        return docs

    def _split_and_tag_chunks(self, raw_docs: List[Document]) -> List[Document]:
        splitter = self._splitter()
        chunks = splitter.split_documents(raw_docs)
        for i, ch in enumerate(chunks):
            md = dict(ch.metadata or {})
            md["chunk_index"] = i
            ch.metadata = md
            ch.page_content = _chunk_embed_text(ch)
        return chunks

    def _chunks_from_vectorstore(self) -> List[Document]:
        """从已加载 FAISS docstore 还原 chunk 列表，保证与向量行对齐。"""
        if self._vectorstore is None:
            return []
        docstore = self._vectorstore.docstore
        mapping = getattr(docstore, "_dict", None)
        if not isinstance(mapping, dict) or not mapping:
            return []
        keys = sorted(mapping.keys(), key=lambda k: (len(k), k))
        chunks: List[Document] = []
        for i, key in enumerate(keys):
            ch = mapping[key]
            md = dict(ch.metadata or {})
            md["chunk_index"] = i
            chunks.append(
                Document(page_content=str(ch.page_content or ""), metadata=md)
            )
        return chunks

    def _rebuild_bm25(self) -> None:
        texts = [c.page_content for c in self._chunks]
        if texts:
            self._bm25.build(texts)
        else:
            self._bm25 = BM25CorpusIndex()

    def _eligible_indices(self, corpus_id: Optional[str]) -> List[int]:
        cid = str(corpus_id or "").strip()
        if not cid:
            return list(range(len(self._chunks)))
        out: List[int] = []
        for i, ch in enumerate(self._chunks):
            md = ch.metadata or {}
            if str(md.get("corpus_id") or "").strip() == cid:
                out.append(i)
        return out

    def _l2_to_similarity(self, dist: float) -> float:
        return 1.0 / (1.0 + max(0.0, float(dist)))

    async def build(self) -> None:
        self._index_source = "none"
        raw_docs = self._load_documents()
        if not raw_docs:
            self._ready = False
            self._vectorstore = None
            self._chunks = []
            self._doc_count = 0
            self._index_source = "none"
            logger.info("知识库文档为空，跳过 Knowledge RAG 索引构建")
            return

        fingerprint = self._documents_fingerprint()
        store_dir = self._faiss_store_dir()
        rebuild = str(os.getenv("KNOWLEDGE_FAISS_REBUILD", "")).strip().lower() in (
            "1",
            "true",
            "yes",
        )
        manifest_path = self._manifest_path()
        idx_faiss = store_dir / "index.faiss"
        idx_pkl = store_dir / "index.pkl"

        loaded_disk = False
        if (
            not rebuild
            and manifest_path.is_file()
            and idx_faiss.is_file()
            and idx_pkl.is_file()
        ):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if self._manifest_matches(data, docs_fingerprint=fingerprint):
                    embeddings = OpenAIEmbeddings(model=self._embedding_model)
                    self._vectorstore = FAISS.load_local(
                        str(store_dir),
                        embeddings,
                        allow_dangerous_deserialization=True,
                    )
                    self._chunks = self._chunks_from_vectorstore()
                    if not self._chunks:
                        self._chunks = self._split_and_tag_chunks(raw_docs)
                    self._rebuild_bm25()
                    self._doc_count = len(self._chunks)
                    self._ready = True
                    self._index_source = "disk"
                    loaded_disk = True
                    logger.info(
                        "Knowledge RAG 从磁盘加载：dir=%s chunks=%s",
                        store_dir,
                        self._doc_count,
                    )
            except Exception as e:
                logger.warning("Knowledge RAG 本地索引加载失败，将重建：%s", e)

        if not loaded_disk:
            self._chunks = self._split_and_tag_chunks(raw_docs)
            if not self._chunks:
                self._ready = False
                self._vectorstore = None
                self._doc_count = 0
                self._index_source = "none"
                logger.info("知识库分块结果为空，跳过 Knowledge RAG 索引构建")
                return
            embeddings = OpenAIEmbeddings(model=self._embedding_model)
            self._vectorstore = await FAISS.afrom_documents(self._chunks, embeddings)
            self._ready = True
            self._doc_count = len(self._chunks)
            self._index_source = "rebuilt"
            try:
                store_dir.mkdir(parents=True, exist_ok=True)
                self._vectorstore.save_local(str(store_dir))
                manifest = self._expected_manifest(docs_fingerprint=fingerprint)
                manifest["chunk_count"] = self._doc_count
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(
                    "Knowledge RAG 索引已落盘：dir=%s chunks=%s",
                    store_dir,
                    self._doc_count,
                )
            except Exception as e:
                logger.warning("Knowledge RAG 落盘失败（内存索引仍可用）：%s", e)

        self._rebuild_bm25()
        logger.info(
            "Knowledge RAG 索引构建完成：chunks=%s bm25=%s",
            self._doc_count,
            self._bm25.ready,
        )

    def _chunk_index_from_doc(self, doc: Document) -> int:
        md = doc.metadata or {}
        if "chunk_index" in md:
            try:
                return int(md["chunk_index"])
            except (TypeError, ValueError):
                pass
        for i, ch in enumerate(self._chunks):
            if ch.page_content == doc.page_content and (ch.metadata or {}) == (doc.metadata or {}):
                return i
        return -1

    async def retrieve_scored(
        self,
        query: str,
        *,
        top_k: int = 6,
        corpus_id: Optional[str] = None,
        initial_k: Optional[int] = None,
    ) -> List[ScoredChunk]:
        if not self.ready or self._vectorstore is None:
            return []
        want_k = max(1, min(20, int(top_k)))
        init_k = initial_k if initial_k is not None else retrieve_initial_k()
        init_k = max(init_k, want_k)
        cid = str(corpus_id or "").strip() or None
        eligible = self._eligible_indices(cid)

        if not hybrid_enabled() or not self._bm25.ready or not eligible:
            pairs = await self._vectorstore.asimilarity_search_with_score(query, k=init_k)
            out: List[ScoredChunk] = []
            for doc, dist in pairs:
                idx = self._chunk_index_from_doc(doc)
                if cid and idx >= 0:
                    md = self._chunks[idx].metadata or {}
                    if str(md.get("corpus_id") or "").strip() != cid:
                        continue
                sim = self._l2_to_similarity(dist)
                out.append(
                    ScoredChunk(
                        document=doc,
                        score=float(dist),
                        fusion_score=sim,
                        vector_score=sim,
                    )
                )
                if len(out) >= want_k:
                    break
            return out

        alpha = hybrid_alpha()
        vec_pairs = await self._vectorstore.asimilarity_search_with_score(
            query, k=min(80, init_k * 3)
        )
        vec_hits: List[Tuple[int, float]] = []
        for doc, dist in vec_pairs:
            idx = self._chunk_index_from_doc(doc)
            if idx < 0 or idx not in eligible:
                continue
            vec_hits.append((idx, self._l2_to_similarity(dist)))
        vec_hits = vec_hits[:init_k]

        bm25_hits = self._bm25.search(query, allowed_indices=eligible, top_k=init_k)
        fused = fuse_vector_bm25(vec_hits, bm25_hits, alpha=alpha, top_k=init_k)

        if rerank_enabled() and fused:
            passages = [self._chunks[h.index].page_content for h in fused]
            fused = apply_rerank_to_hits(query, fused, passages, top_n=want_k)
        else:
            fused = fused[:want_k]

        scored: List[ScoredChunk] = []
        for h in fused:
            if h.index < 0 or h.index >= len(self._chunks):
                continue
            ch = self._chunks[h.index]
            primary = h.rerank_score if h.rerank_score is not None else h.fusion_score
            scored.append(
                ScoredChunk(
                    document=ch,
                    score=float(primary),
                    fusion_score=h.fusion_score,
                    vector_score=h.vector_score,
                    bm25_score=h.bm25_score,
                    rerank_score=h.rerank_score,
                )
            )
        return scored

    async def retrieve_with_scores(
        self,
        query: str,
        *,
        top_k: int = 6,
        corpus_id: Optional[str] = None,
    ) -> List[Tuple[Document, float]]:
        """兼容旧接口：返回 (文档, score)；有 rerank 时 score 为 rerank 分。"""
        rows = await self.retrieve_scored(query, top_k=top_k, corpus_id=corpus_id)
        return [(r.document, r.score) for r in rows]

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        corpus_id: Optional[str] = None,
    ) -> List[Document]:
        rows = await self.retrieve_scored(query, top_k=top_k, corpus_id=corpus_id)
        return [r.document for r in rows]

    @staticmethod
    def _format_citations(docs: List[Document]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        seen: set[str] = set()
        for d in docs:
            md = d.metadata or {}
            corpus_id = str(md.get("corpus_id") or "").strip()
            doc_id = str(md.get("doc_id") or "").strip()
            key = f"{corpus_id}:{doc_id}"
            if not corpus_id or not doc_id or key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "source": str(md.get("source_url") or f"knowledge:{corpus_id}/{doc_id}"),
                    "title": str(md.get("title") or doc_id),
                    "corpus_id": corpus_id,
                    "doc_id": doc_id,
                    "lang": str(md.get("lang") or ""),
                }
            )
        return out[:12]

    @staticmethod
    def _token_chunk_to_text(chunk: Any) -> str:
        if chunk is None:
            return ""
        if isinstance(chunk, str):
            return chunk
        content = getattr(chunk, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            return "".join(parts)
        return ""

    async def stream_answer_with_stuff(
        self,
        *,
        query: str,
        docs: List[Document],
        answer_language: str,
    ) -> AsyncIterator[str]:
        llm = ChatOpenAI(
            model=self._chat_model,
            temperature=0.2,
            streaming=True,
        )
        prompt = _knowledge_qa_stuff_prompt_template()
        chain = create_stuff_documents_chain(llm=llm, prompt=prompt)
        async for chunk in chain.astream(
            {
                "input": query,
                "answer_language": answer_language,
                "context": docs,
            }
        ):
            piece = self._token_chunk_to_text(chunk)
            if piece:
                yield piece

    async def answer_with_stuff(
        self,
        *,
        query: str,
        docs: List[Document],
        answer_language: str,
    ) -> Tuple[str, List[Dict[str, str]]]:
        if not docs:
            no_ctx = (
                "当前知识库未检索到足够上下文，建议你补充更具体的技术对象、场景或约束条件。"
                if answer_language in ("zh", "mixed")
                else "No sufficient knowledge context was retrieved. Please provide more specific technical scope."
            )
            return no_ctx, []
        llm = ChatOpenAI(model=self._chat_model, temperature=0.2)
        prompt = _knowledge_qa_stuff_prompt_template()
        chain = create_stuff_documents_chain(llm=llm, prompt=prompt)
        answer = await chain.ainvoke(
            {
                "input": query,
                "answer_language": answer_language,
                "context": docs,
            }
        )
        text = str(answer).strip()
        return text, self._format_citations(docs)
