"""知识库 RAG：基于 LangChain + FAISS 的检索与 stuff 问答链。"""

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

logger = logging.getLogger(__name__)

KNOWLEDGE_QA_SYSTEM_PROMPT = """你是技术面试 Tutor。请严格基于提供的知识库片段回答，不要编造未在片段中出现的事实。

要求：
1. 回答语言遵循 answer_language（zh/en/mixed）。
2. mixed 模式：先中文结论，再给简短 English 补充。
3. 如果上下文不足，请明确说明信息不足，并给出可继续追问的方向。
4. 回答用 Markdown，结构清晰，尽量简洁。
"""

# create_stuff_documents_chain 要求 human 模板含 {context}，由链注入拼接后的文档正文
_KNOWLEDGE_STUFF_HUMAN = (
    "answer_language={answer_language}\n\n"
    "用户问题：{input}\n\n"
    "知识库片段：\n{context}\n\n"
    "请严格基于上述片段回答。"
)


def _knowledge_qa_stuff_prompt_template() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", KNOWLEDGE_QA_SYSTEM_PROMPT),
            ("human", _KNOWLEDGE_STUFF_HUMAN),
        ]
    )


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
        self._doc_count = 0

    @property
    def ready(self) -> bool:
        return self._ready and self._vectorstore is not None

    @property
    def doc_count(self) -> int:
        return self._doc_count

    def _load_documents(self) -> List[Document]:
        """从 knowledge/documents 读取规范化文档 JSON。"""
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
            # topic_slugs 主要服务题库白名单；知识库检索不按其过滤，避免误伤召回。
            topic_slugs = data.get("topic_slugs") or []
            if not isinstance(topic_slugs, list):
                topic_slugs = []
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
                    },
                )
            )
        return docs

    async def build(self) -> None:
        """加载文档、分块并构建 FAISS。"""
        raw_docs = self._load_documents()
        if not raw_docs:
            self._ready = False
            self._vectorstore = None
            self._doc_count = 0
            logger.info("知识库文档为空，跳过 Knowledge RAG 索引构建")
            return
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=180,
            separators=["\n## ", "\n### ", "\n\n", "\n", "。", ".", " ", ""],
        )
        chunks = splitter.split_documents(raw_docs)
        if not chunks:
            self._ready = False
            self._vectorstore = None
            self._doc_count = 0
            logger.info("知识库分块结果为空，跳过 Knowledge RAG 索引构建")
            return
        # 每个分块嵌入前带上文档标题，便于「按标题语义」与正文一起被向量检索命中。
        for ch in chunks:
            md = ch.metadata or {}
            t = str(md.get("title") or "").strip()
            if t:
                ch.page_content = f"Title: {t}\n\n{ch.page_content}"
        embeddings = OpenAIEmbeddings(model=self._embedding_model)
        self._vectorstore = await FAISS.afrom_documents(chunks, embeddings)
        self._ready = True
        self._doc_count = len(chunks)
        logger.info("Knowledge RAG 索引构建完成：chunks=%s", self._doc_count)

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        corpus_id: Optional[str] = None,
    ) -> List[Document]:
        """统一知识库检索：默认单次召回；可按 corpus_id 缩小范围。"""
        if not self.ready or self._vectorstore is None:
            return []
        want_k = max(1, min(20, int(top_k)))
        cid = str(corpus_id or "").strip()
        # 有过滤时多取一些再截断，避免向量 Top-K 全落在其它 corpus。
        fetch_k = min(80, want_k * 6) if cid else want_k
        fetch_k = max(fetch_k, want_k)
        docs = await self._vectorstore.asimilarity_search(query, k=fetch_k)
        if cid:
            docs = [
                d
                for d in docs
                if str((d.metadata or {}).get("corpus_id") or "").strip() == cid
            ]
        return docs[:want_k]

    @staticmethod
    def _format_citations(docs: List[Document]) -> List[Dict[str, str]]:
        """从检索片段提取去重引用元信息。"""
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
        """从 LangChain 流式 chunk 中取出可拼接的正文增量。"""
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
        """与 answer_with_stuff 同链路，按 token 增量产出正文（docs 须非空）。"""
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
        """基于已检索文档执行 stuff 问答链。"""
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
