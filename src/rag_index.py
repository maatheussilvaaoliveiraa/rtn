"""
rag_index.py
------------
PASSO 3 do pipeline (track NÃO estruturado): transformar o texto do PDF
em conhecimento pesquisável pelo LLM.

Fluxo: texto limpo -> CHUNKING -> EMBEDDINGS -> pgvector (Neon).

Conceitos rápidos:
  - Chunking: quebrar o texto em pedaços de ~1000 caracteres com
    sobreposição. Pedaços grandes demais "diluem" o significado; pequenos
    demais perdem contexto. A sobreposição evita cortar uma ideia ao meio.
  - Embedding: transformar cada pedaço em um vetor de números que
    representa seu SIGNIFICADO. Textos parecidos => vetores próximos.
  - pgvector: extensão do Postgres que guarda esses vetores e faz busca
    por similaridade (o coração do "Retrieval" no RAG).
"""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_postgres import PGVector
from sqlalchemy import create_engine, text

from . import config


def get_embeddings() -> FastEmbedEmbeddings:
    """Modelo de embeddings local (roda no Actions e no Streamlit)."""
    return FastEmbedEmbeddings(model_name=config.EMBEDDING_MODEL)


def get_vectorstore() -> PGVector:
    """Conecta ao vector store no Neon (cria as tabelas se não existirem)."""
    return PGVector(
        embeddings=get_embeddings(),
        collection_name=config.VECTOR_COLLECTION,
        connection=config.DATABASE_URL,
        use_jsonb=True,
    )


def _chunk(texto: str, mes_referencia: str) -> list[Document]:
    """Quebra o texto em chunks e anexa metadados (de que mês ele veio)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        # Tenta quebrar em fronteiras "naturais", nesta ordem de prioridade.
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    pedacos = splitter.split_text(texto)
    return [
        Document(
            page_content=p,
            metadata={"mes_referencia": mes_referencia, "fonte": "RTN", "chunk": i},
        )
        for i, p in enumerate(pedacos)
    ]


def _limpar_mes_anterior(mes_referencia: str) -> None:
    """Idempotência: apaga chunks já existentes desse mês antes de reinserir.

    Por quê: se o pipeline rodar duas vezes para o mesmo mês (ex.: retrigger
    manual), não queremos vetores duplicados poluindo a busca.
    """
    engine = create_engine(config.DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM langchain_pg_embedding "
                "WHERE cmetadata->>'mes_referencia' = :mes"
            ),
            {"mes": mes_referencia},
        )
    engine.dispose()


def indexar(texto_limpo: str, mes_referencia: str) -> int:
    """Indexa o texto de um mês no pgvector. Retorna nº de chunks gravados."""
    docs = _chunk(texto_limpo, mes_referencia)
    if not docs:
        print("[rag_index] Nenhum chunk gerado (texto vazio?).")
        return 0

    try:
        _limpar_mes_anterior(mes_referencia)  # ignora se a tabela ainda não existe
    except Exception as e:  # noqa: BLE001
        print(f"[rag_index] (ok no 1º run) limpeza pulada: {e}")

    store = get_vectorstore()
    store.add_documents(docs)
    print(f"[rag_index] {len(docs)} chunks indexados para {mes_referencia}.")
    return len(docs)


if __name__ == "__main__":
    from .extract import extract_text, limpar_texto

    texto = limpar_texto(extract_text("data/raw/exemplo.pdf"))
    indexar(texto, "2024-01")
