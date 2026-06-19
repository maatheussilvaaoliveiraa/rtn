"""
rag_query.py
------------
O "R-A-G" em ação na hora da pergunta:

  Retrieval  -> busca no pgvector os chunks mais parecidos com a pergunta.
  Augmented  -> injeta esses chunks no prompt do LLM como contexto.
  Generation -> a Groq (Llama) escreve a resposta baseada SÓ nesse contexto.

Regra de ouro: o LLM responde apenas com base no relatório recuperado.
Isso reduz alucinação e deixa a resposta auditável (citamos o mês).
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

from . import config
from .rag_index import get_vectorstore

PROMPT = ChatPromptTemplate.from_template(
    """Você é um analista fiscal. Responda à pergunta usando EXCLUSIVAMENTE
o contexto abaixo, extraído do Resultado do Tesouro Nacional (RTN).
Se a resposta não estiver no contexto, diga que não há informação suficiente
no relatório. Responda em português, de forma objetiva.

Contexto:
{contexto}

Pergunta: {pergunta}

Resposta:"""
)


def _formatar_contexto(docs) -> str:
    blocos = []
    for d in docs:
        mes = d.metadata.get("mes_referencia", "?")
        blocos.append(f"(RTN {mes}) {d.page_content}")
    return "\n\n".join(blocos)


def construir_chain(k: int = 4, mes: str | None = None):
    """Monta a cadeia RAG (LCEL).

    k: quantos chunks recuperar.
    mes: se informado, restringe a busca a um mês específico (filtro pgvector).
    """
    store = get_vectorstore()
    search_kwargs = {"k": k}
    if mes:
        search_kwargs["filter"] = {"mes_referencia": mes}
    retriever = store.as_retriever(search_kwargs=search_kwargs)

    llm = ChatGroq(
        model=config.GROQ_MODEL,
        api_key=config.GROQ_API_KEY,
        temperature=0.1,  # baixa: queremos fidelidade, não criatividade
    )

    return (
        {
            "contexto": retriever | _formatar_contexto,
            "pergunta": RunnablePassthrough(),
        }
        | PROMPT
        | llm
        | StrOutputParser()
    )


def perguntar(pergunta: str, k: int = 4, mes: str | None = None) -> str:
    """Atalho: faz uma pergunta e devolve a resposta em texto."""
    return construir_chain(k=k, mes=mes).invoke(pergunta)


if __name__ == "__main__":
    print(perguntar("Qual foi o resultado primário do mês e por quê?"))
