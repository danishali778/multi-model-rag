from app.domain.entities.rag import SourceCitation


def build_messages(question: str, source_blocks: list[str]) -> list[dict[str, str]]:
    system = (
        "You are a grounded enterprise RAG assistant. "
        "Answer using only the provided context. "
        "If the context is insufficient, say so clearly. "
        "Cite factual claims using the provided source identifiers."
    )
    context = "\n\n".join(source_blocks)
    user = (
        f"Question:\n{question}\n\n"
        f"Context:\n{context}\n\n"
        "Return a concise answer with inline citations like [source:1]."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
