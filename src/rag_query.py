"""
rag_query.py
------------
O "R-A-G" em ação na hora da pergunta:

  Retrieval  -> busca no pgvector os chunks mais parecidos com a pergunta.
  Augmented  -> injeta esses chunks no prompt do LLM como contexto.
  Generation -> a Groq (Llama) escreve a resposta baseada SÓ nesse contexto.

Regra de ouro: o LLM responde apenas com base no relatório recuperado.
Isso reduz alucinação e deixa a resposta auditável (citamos o mês).

Dois cuidados que melhoram MUITO o recall (e que evitam o bug clássico de
"não há informação suficiente" para perguntas simples):

  1) Detecção de mês — se a pergunta cita um mês ("2026-04", "abril de 2026"),
     restringimos a busca àquele mês (filtro no pgvector). Com vários meses
     indexados, isso evita misturar relatórios.
  2) Expansão da query — o texto do relatório fala "abril de 2026", não
     "2026-04". Convertendo a forma numérica para o mês por extenso ANTES de
     embeddar, a busca semântica casa com o texto e recupera a frase certa.
"""

from __future__ import annotations

import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq
from sqlalchemy import create_engine, text

from . import config
from .rag_index import get_vectorstore

PROMPT = ChatPromptTemplate.from_template(
    """Você é um analista fiscal. Responda à pergunta usando EXCLUSIVAMENTE
o contexto abaixo, extraído do Resultado do Tesouro Nacional (RTN). O contexto
tem duas partes: DADOS ESTRUTURADOS (números já curados, priorize-os para
valores exatos) e TRECHOS DO RELATÓRIO (texto para explicações e detalhes).
Distinga sempre resultado DO MÊS de resultado ACUMULADO no ano.
Se a resposta não estiver no contexto, diga que não há informação suficiente
no relatório. Responda em português, de forma objetiva.

{contexto}

Pergunta: {pergunta}

Resposta:"""
)

# Rótulos amigáveis para as métricas estruturadas (fatos_fiscais).
_ROTULOS_METRICA = {
    "receita_total": "Receita Total do Governo Central",
    "receita_liquida": "Receita Líquida do Governo Central",
    "despesa_total": "Despesa Total do Governo Central",
    "resultado_primario_governo_central": "Resultado primário do Governo Central",
    "resultado_nominal_governo_central": "Resultado nominal do Governo Central",
}
# Métricas que são SALDOS (sinal vira superávit/déficit). As demais (receita,
# despesa) são sempre positivas e apresentadas como valor simples.
_METRICAS_SALDO = {
    "resultado_primario_governo_central",
    "resultado_nominal_governo_central",
}

# Meses por extenso <-> número, usados na detecção e na expansão da query.
_MESES = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}
_MES_NUM = {v: k for k, v in _MESES.items()}
# aceita variações sem acento comuns na digitação
_MES_NUM.update({"marco": 3})


def _detectar_mes(pergunta: str) -> str | None:
    """Extrai um mês de referência ('AAAA-MM') citado na pergunta, se houver.

    Reconhece "2026-04", "2026/04" e "abril de 2026" / "abril/2026".
    """
    # Forma numérica: AAAA-MM ou AAAA/MM.
    m = re.search(r"(20\d{2})[-/](0[1-9]|1[0-2])", pergunta)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    # Forma por extenso: "<mês> de 2026" / "<mês>/2026" / "<mês> 2026".
    nomes = "|".join(_MES_NUM.keys())
    m = re.search(rf"\b({nomes})\b\s*(?:de\s*|/\s*)?(20\d{{2}})", pergunta, re.IGNORECASE)
    if m:
        num = _MES_NUM[m.group(1).lower()]
        return f"{m.group(2)}-{num:02d}"
    return None


def _expandir_pergunta(pergunta: str) -> str:
    """Reescreve datas numéricas como mês por extenso para casar com o texto.

    Ex.: "qual o resultado primário de 2026-04?" ->
         "qual o resultado primário de abril de 2026 (2026-04)?"
    Mantém a forma original também, para não perder nenhum sinal.
    """
    def _sub(m: re.Match) -> str:
        ano, mes = m.group(1), int(m.group(2))
        return f"{_MESES[mes]} de {ano} ({ano}-{m.group(2)})"

    return re.sub(r"(20\d{2})[-/](0[1-9]|1[0-2])", _sub, pergunta)


def _formatar_contexto(docs) -> str:
    blocos = []
    for d in docs:
        mes = d.metadata.get("mes_referencia", "?")
        blocos.append(f"(RTN {mes}) {d.page_content}")
    return "\n\n".join(blocos)


def _contexto_estruturado(mes: str | None) -> str:
    """Lê os saldos curados de fatos_fiscais para o mês e formata como texto.

    Esse é o lado "estruturado" do RAG híbrido: garante que os números-chave
    (com o sinal já interpretado como superávit/déficit) estejam SEMPRE no
    contexto, mesmo que a busca semântica no texto não traga o trecho exato.
    """
    if not mes:
        return ""
    engine = create_engine(config.DATABASE_URL)
    with engine.connect() as conn:
        linhas = conn.execute(
            text(
                "SELECT metrica, valor, unidade FROM fatos_fiscais "
                "WHERE mes_referencia = :mes ORDER BY metrica"
            ),
            {"mes": mes},
        ).fetchall()
    engine.dispose()
    if not linhas:
        return ""

    itens = []
    for metrica, valor, _unidade in linhas:
        # valores vêm em R$ milhões; apresentamos em R$ bilhões (mais legível).
        v_bi = float(valor) / 1000.0
        rotulo = _ROTULOS_METRICA.get(metrica, metrica)
        num_br = f"{abs(v_bi):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if metrica in _METRICAS_SALDO:
            sinal = "superávit" if v_bi >= 0 else "déficit"
            itens.append(f"- {rotulo}: {sinal} de R$ {num_br} bilhões")
        else:
            itens.append(f"- {rotulo}: R$ {num_br} bilhões")
    return f"DADOS ESTRUTURADOS (RTN {mes}, valores correntes):\n" + "\n".join(itens)


def _recuperar(pergunta: str, k: int, mes: str | None):
    """Recupera chunks. Se um mês foi detectado, filtra por ele; mas se nada
    vier (mês não indexado, p.ex.), faz fallback sem filtro para não falhar."""
    store = get_vectorstore()
    consulta = _expandir_pergunta(pergunta)

    if mes:
        docs = store.similarity_search(consulta, k=k, filter={"mes_referencia": mes})
        if docs:
            return docs
    return store.similarity_search(consulta, k=k)


def perguntar(pergunta: str, k: int = 8, mes: str | None = None) -> str:
    """Faz uma pergunta ao relatório e devolve a resposta em texto.

    Usa RAG híbrido: contexto = dados estruturados do mês (números curados) +
    trechos do texto recuperados por similaridade. k: nº de trechos de texto.
    mes: força um mês; se None, detectamos a partir da própria pergunta.
    """
    mes = mes or _detectar_mes(pergunta)
    docs = _recuperar(pergunta, k=k, mes=mes)

    partes = []
    estruturado = _contexto_estruturado(mes)
    if estruturado:
        partes.append(estruturado)
    partes.append("TRECHOS DO RELATÓRIO:\n" + _formatar_contexto(docs))
    contexto = "\n\n".join(partes)

    llm = ChatGroq(
        model=config.GROQ_MODEL,
        api_key=config.GROQ_API_KEY,
        temperature=0.1,  # baixa: queremos fidelidade, não criatividade
    )
    chain = PROMPT | llm | StrOutputParser()
    return chain.invoke({"contexto": contexto, "pergunta": pergunta})


if __name__ == "__main__":
    print(perguntar("qual o resultado primário de 2026-04?"))
