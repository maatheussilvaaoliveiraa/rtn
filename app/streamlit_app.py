"""
streamlit_app.py
----------------
A CAMADA DE APRESENTAÇÃO do projeto, publicada no Streamlit Community Cloud.

Duas abas, espelhando os dois tracks do pipeline:
  📊 Dashboard -> lê a tabela fatos_fiscais (números) e desenha gráficos.
  💬 Chat      -> faz perguntas em linguagem natural sobre o relatório (RAG).

Observação de deploy: o Streamlit Cloud roda este arquivo a partir da RAIZ do
repositório, então precisamos colocar a raiz no sys.path para conseguir
importar o pacote `src`. Os segredos (DATABASE_URL, GROQ_API_KEY) entram em
Settings → Secrets do app, no mesmo formato do .env.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garante que `import src...` funcione independente de onde o Streamlit rodar.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text

from src import config

st.set_page_config(page_title="RTN — Resultado do Tesouro Nacional", page_icon="📊", layout="wide")


# ---------------------------------------------------------------------------
# Acesso a dados (com cache do Streamlit para não martelar o Neon a cada clique)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_engine():
    """Engine SQLAlchemy reutilizada entre reruns (cache_resource = singleton)."""
    return create_engine(config.DATABASE_URL)


@st.cache_data(ttl=600)
def carregar_fatos() -> pd.DataFrame:
    """Lê fatos_fiscais em formato 'tidy'. Cache de 10 min (ttl=600)."""
    engine = get_engine()
    with engine.connect() as conn:
        df = pd.read_sql(
            text(
                "SELECT mes_referencia, metrica, valor, unidade "
                "FROM fatos_fiscais ORDER BY mes_referencia, metrica"
            ),
            conn,
        )
    return df


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("📊 Resultado do Tesouro Nacional (RTN)")
st.caption(
    "Pipeline automatizado: baixa o Sumário Executivo do RTN, estrutura os "
    "números e indexa o texto para um chat com IA. Projeto de portfólio."
)

aba_dash, aba_chat = st.tabs(["📊 Dashboard", "💬 Pergunte ao relatório"])

# --- Aba 1: Dashboard --------------------------------------------------------
with aba_dash:
    try:
        df = carregar_fatos()
    except Exception as e:  # noqa: BLE001
        st.error(f"Não consegui ler o banco: {type(e).__name__}. "
                 "Verifique o secret DATABASE_URL.")
        df = pd.DataFrame()

    if df.empty:
        st.info("Ainda não há dados. Rode o pipeline (`python pipeline.py`) "
                "ou aguarde a próxima execução do GitHub Actions.")
    else:
        meses = sorted(df["mes_referencia"].unique())
        col_a, col_b = st.columns([1, 3])
        with col_a:
            mes_sel = st.selectbox("Mês de referência", meses, index=len(meses) - 1)

        # Cartões com as métricas do mês selecionado.
        do_mes = df[df["mes_referencia"] == mes_sel]
        st.subheader(f"Indicadores — {mes_sel}")
        cols = st.columns(max(len(do_mes), 1))
        for col, (_, linha) in zip(cols, do_mes.iterrows()):
            rotulo = linha["metrica"].replace("_", " ").title()
            col.metric(rotulo, f"{linha['valor']:,.1f}", help=linha["unidade"])

        # Série temporal por métrica (faz sentido quando há vários meses).
        st.subheader("Evolução no tempo")
        metricas = sorted(df["metrica"].unique())
        metrica_sel = st.selectbox(
            "Métrica", metricas,
            format_func=lambda m: m.replace("_", " ").title(),
        )
        serie = df[df["metrica"] == metrica_sel]
        if len(serie) > 1:
            fig = px.line(
                serie, x="mes_referencia", y="valor", markers=True,
                labels={"mes_referencia": "Mês", "valor": serie["unidade"].iloc[0]},
                title=metrica_sel.replace("_", " ").title(),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            fig = px.bar(
                serie, x="mes_referencia", y="valor",
                labels={"mes_referencia": "Mês", "valor": serie["unidade"].iloc[0]},
                title=metrica_sel.replace("_", " ").title(),
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Só há um mês de dados — a série temporal aparece quando "
                       "o pipeline acumular mais execuções mensais.")

        with st.expander("Ver dados brutos"):
            st.dataframe(df, use_container_width=True)

# --- Aba 2: Chat RAG ---------------------------------------------------------
with aba_chat:
    st.subheader("Pergunte sobre o relatório")
    st.caption("As respostas usam EXCLUSIVAMENTE o texto do RTN indexado "
               "(RAG), reduzindo alucinação. Powered by Groq + pgvector.")

    pergunta = st.text_input(
        "Sua pergunta",
        placeholder="Ex.: Qual foi o resultado primário do mês e por quê?",
    )

    if pergunta:
        # Import tardio: só carrega o stack do LLM quando o usuário pergunta,
        # deixando o load inicial do dashboard mais leve.
        try:
            from src.rag_query import perguntar

            with st.spinner("Consultando o relatório..."):
                resposta = perguntar(pergunta)
            st.markdown(resposta)
        except Exception as e:  # noqa: BLE001
            st.error(f"Não consegui responder: {type(e).__name__}. "
                     "Verifique os secrets GROQ_API_KEY e DATABASE_URL e se o "
                     "texto já foi indexado pelo pipeline.")
