"""
streamlit_app.py
----------------
A CAMADA DE APRESENTAÇÃO do projeto, publicada no Streamlit Community Cloud.

Duas abas, espelhando os dois tracks do pipeline:
  📊 Dashboard -> lê fatos_fiscais (série histórica oficial) e desenha gráficos:
                 KPIs com variação YoY, série temporal e comparação ano-a-ano.
  💬 Chat      -> perguntas em linguagem natural sobre o relatório (RAG híbrido).

Observação de deploy: o Streamlit Cloud roda este arquivo a partir da RAIZ do
repositório, então colocamos a raiz no sys.path para importar o pacote `src`.
Os segredos (DATABASE_URL, GROQ_API_KEY) entram em Settings → Secrets do app.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garante que `import src...` funcione independente de onde o Streamlit rodar.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text

from src import config

st.set_page_config(
    page_title="RTN — Resultado do Tesouro Nacional",
    page_icon="📊",
    layout="wide",
)

# Paleta e rótulos -----------------------------------------------------------
AZUL, VERDE, VERMELHO, CINZA = "#1f4e79", "#2e8b57", "#c0392b", "#7f8c8d"

LABELS = {
    "receita_total": "Receita Total",
    "receita_liquida": "Receita Líquida",
    "despesa_total": "Despesa Total",
    "resultado_primario_governo_central": "Resultado Primário",
    "resultado_nominal_governo_central": "Resultado Nominal",
}
# ordem de exibição dos KPIs
ORDEM = list(LABELS.keys())
SALDOS = {"resultado_primario_governo_central", "resultado_nominal_governo_central"}


# Acesso a dados (com cache para não martelar o Neon) ------------------------
@st.cache_resource
def get_engine():
    return create_engine(config.DATABASE_URL)


@st.cache_data(ttl=600)
def carregar_fatos() -> pd.DataFrame:
    """Lê fatos_fiscais. Valores vêm em R$ milhões; criamos também R$ bilhões."""
    engine = get_engine()
    with engine.connect() as conn:
        df = pd.read_sql(
            text(
                "SELECT mes_referencia, metrica, valor FROM fatos_fiscais "
                "ORDER BY mes_referencia"
            ),
            conn,
        )
    if df.empty:
        return df
    df["valor_bi"] = df["valor"] / 1000.0
    df["data"] = pd.to_datetime(df["mes_referencia"] + "-01")
    df["rotulo"] = df["metrica"].map(LABELS).fillna(df["metrica"])
    return df


def _fmt_bi(v: float) -> str:
    """Formata um número em R$ bilhões no padrão brasileiro (1.234,5)."""
    return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# Cabeçalho
# ---------------------------------------------------------------------------
st.title("RTN - RESULTADO DO TESOURO NACIONAL")
st.caption(
    "Pipeline automatizado: estrutura a série histórica oficial do RTN e indexa "
    "o Sumário Executivo para um chat com IA. Valores em R$ bilhões correntes."
)

df = carregar_fatos()

aba_dash, aba_chat = st.tabs(["📊 Dashboard", "💬 Pergunte ao relatório"])

# ===========================================================================
# ABA 1 — DASHBOARD
# ===========================================================================
with aba_dash:
    if df.empty:
        st.info("Ainda não há dados. Rode o pipeline (`python pipeline.py`) "
                "ou aguarde a próxima execução do GitHub Actions.")
    else:
        meses = sorted(df["mes_referencia"].unique())
        anos = sorted({m[:4] for m in meses})

        # --- Controles ---
        c1, c2 = st.columns([1, 3])
        with c1:
            mes_sel = st.selectbox("Mês de referência", meses, index=len(meses) - 1)

        # ---------------------------------------------------------------
        # KPIs com variação YoY (vs mesmo mês do ano anterior)
        # ---------------------------------------------------------------
        ano, mm = mes_sel.split("-")
        mes_yoy = f"{int(ano) - 1}-{mm}"
        atual = df[df["mes_referencia"] == mes_sel].set_index("metrica")["valor_bi"]
        anterior = df[df["mes_referencia"] == mes_yoy].set_index("metrica")["valor_bi"]

        st.subheader(f"Indicadores — {mes_sel}  ·  R$ bilhões")
        cols = st.columns(len(ORDEM))
        for col, metrica in zip(cols, ORDEM):
            if metrica not in atual.index:
                continue
            val = float(atual[metrica])
            delta = None
            if metrica in anterior.index:
                d = val - float(anterior[metrica])
                delta = f"{'+' if d >= 0 else '−'}{_fmt_bi(abs(d))} vs {mes_yoy}"
            col.metric(LABELS[metrica], _fmt_bi(val), delta=delta)

        st.divider()

        # ---------------------------------------------------------------
        # Resultado primário ao longo do tempo (superávit verde / déficit vermelho)
        # ---------------------------------------------------------------
        st.subheader("Resultado primário do Governo Central")
        c3, c4 = st.columns([1, 3])
        with c3:
            faixa = st.select_slider(
                "Período (anos)",
                options=anos,
                value=(anos[max(0, len(anos) - 4)], anos[-1]),
            )
        ini, fim = faixa
        rp = df[(df["metrica"] == "resultado_primario_governo_central")
                & (df["mes_referencia"].str[:4] >= ini)
                & (df["mes_referencia"].str[:4] <= fim)].sort_values("data")
        cores = [VERDE if v >= 0 else VERMELHO for v in rp["valor_bi"]]
        fig = go.Figure(go.Bar(
            x=rp["data"], y=rp["valor_bi"], marker_color=cores,
            hovertemplate="%{x|%b/%Y}<br>R$ %{y:.1f} bi<extra></extra>",
        ))
        fig.update_layout(
            template="plotly_white", height=340,
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title="R$ bilhões", xaxis_title=None,
        )
        fig.add_hline(y=0, line_color=CINZA, line_width=1)
        st.plotly_chart(fig, use_container_width=True)

        # ---------------------------------------------------------------
        # Receita x Despesa (linhas)
        # ---------------------------------------------------------------
        st.subheader("Receita Líquida × Despesa Total")
        rd = df[df["metrica"].isin(["receita_liquida", "despesa_total"])
                & (df["mes_referencia"].str[:4] >= ini)
                & (df["mes_referencia"].str[:4] <= fim)].sort_values("data")
        fig2 = px.line(
            rd, x="data", y="valor_bi", color="rotulo", markers=False,
            template="plotly_white",
            color_discrete_map={"Receita Líquida": AZUL, "Despesa Total": VERMELHO},
            labels={"valor_bi": "R$ bilhões", "data": "", "rotulo": ""},
        )
        fig2.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                           legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig2, use_container_width=True)

        # ---------------------------------------------------------------
        # Comparação YoY: a métrica escolhida no mês escolhido, ano a ano
        # ---------------------------------------------------------------
        st.subheader("Comparação ano a ano (mesmo mês)")
        metrica_yoy = st.selectbox(
            "Métrica", ORDEM, format_func=lambda m: LABELS[m],
        )
        serie_mm = df[(df["metrica"] == metrica_yoy)
                      & (df["mes_referencia"].str[5:7] == mm)].sort_values("data")
        cor = ([VERDE if v >= 0 else VERMELHO for v in serie_mm["valor_bi"]]
               if metrica_yoy in SALDOS else AZUL)
        fig3 = go.Figure(go.Bar(
            x=serie_mm["mes_referencia"].str[:4], y=serie_mm["valor_bi"],
            marker_color=cor, text=[_fmt_bi(v) for v in serie_mm["valor_bi"]],
            textposition="outside",
            hovertemplate="%{x}<br>R$ %{y:.1f} bi<extra></extra>",
        ))
        fig3.update_layout(
            template="plotly_white", height=340,
            margin=dict(l=10, r=10, t=30, b=10),
            yaxis_title="R$ bilhões",
            title=f"{LABELS[metrica_yoy]} — mês {mm}, por ano",
        )
        fig3.add_hline(y=0, line_color=CINZA, line_width=1)
        st.plotly_chart(fig3, use_container_width=True)

        with st.expander("Ver dados brutos"):
            tabela = df[["mes_referencia", "rotulo", "valor", "valor_bi"]].rename(
                columns={"rotulo": "métrica", "valor": "R$ milhões",
                         "valor_bi": "R$ bilhões"})
            st.dataframe(tabela, use_container_width=True, hide_index=True)

# ===========================================================================
# ABA 2 — CHAT RAG
# ===========================================================================
with aba_chat:
    st.subheader("Pergunte sobre o relatório")
    st.caption("Respostas combinam os números curados (dados estruturados) com "
               "trechos do texto do RTN (RAG). Powered by Groq + pgvector.")

    pergunta = st.text_input(
        "Sua pergunta",
        placeholder="Ex.: qual o resultado primário de 2026-04?",
    )

    if pergunta:
        # Import tardio: só carrega o stack do LLM quando o usuário pergunta.
        try:
            from src.rag_query import perguntar

            with st.spinner("Consultando o relatório..."):
                resposta = perguntar(pergunta)
            st.markdown(resposta)
        except Exception as e:  # noqa: BLE001
            st.error(f"Não consegui responder: {type(e).__name__}. "
                     "Verifique os secrets GROQ_API_KEY e DATABASE_URL e se o "
                     "texto já foi indexado pelo pipeline.")
