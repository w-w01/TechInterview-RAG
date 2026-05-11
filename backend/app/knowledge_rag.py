"""知识库 RAG：基于 LangChain + FAISS 的检索与 stuff 问答链。"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

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
        embeddings = OpenAIEmbeddings(model=self._embedding_model)
        self._vectorstore = await FAISS.afrom_documents(chunks, embeddings)
        self._ready = True
        self._doc_count = len(chunks)
        logger.info("Knowledge RAG 索引构建完成：chunks=%s", self._doc_count)

    async def retrieve(self, query: str, *, top_k: int = 6) -> List[Document]:
        """统一知识库检索：默认单次召回，不做重复搜索。"""
        if not self.ready or self._vectorstore is None:
            return []
        k = max(1, min(20, int(top_k)))
        return await self._vectorstore.asimilarity_search(query, k=k)

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
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", KNOWLEDGE_QA_SYSTEM_PROMPT),
                (
                    "human",
                    "answer_language={answer_language}\n\n用户问题：{input}\n\n请基于 context 回答。",
                ),
            ]
        )
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
