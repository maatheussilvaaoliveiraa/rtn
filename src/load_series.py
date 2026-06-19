"""
load_series.py
--------------
Track ESTRUTURADO (fonte de verdade): carrega a série histórica oficial do RTN
(planilha .xlsx publicada pelo Tesouro) na tabela `fatos_fiscais`.

Por que a planilha e não o PDF? O Sumário Executivo é narrativo e enuncia só
alguns saldos, com redação que varia mês a mês (extração por regex fica frágil
no histórico). Já a planilha "série histórica" traz, de forma tabular e
consistente, TODA a série mensal desde 1997 — receita, despesa, resultado
primário e nominal. É a fonte certa para o dashboard (série temporal + YoY).
O PDF segue sendo a fonte do CHAT (RAG), para as explicações qualitativas.

Layout da aba "1.1" (Resultado Primário do Governo Central - Mensal, R$ milhões
correntes): uma linha de cabeçalho "Discriminação" com uma coluna por mês
(datas), e cada linha seguinte é uma rubrica. Pegamos as rubricas-manchete.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from .models import FatoFiscal, carregar

# Aba e janela temporal (decisão: ~6 anos de histórico).
ABA = "1.1"
DESDE = "2020-01"
UNIDADE = "R$ milhões"

# metrica -> regex que casa o rótulo da rubrica na coluna "Discriminação".
# Ancoramos no número da linha p/ não casar sub-rubricas.
METRICAS_LINHA: dict[str, str] = {
    "receita_total": r"^\s*1\.\s*RECEITA TOTAL",
    "receita_liquida": r"^\s*3\.\s*RECEITA L[IÍ]QUIDA",
    "despesa_total": r"^\s*4\.\s*DESPESA TOTAL",
    "resultado_primario_governo_central":
        r"^\s*5\.\s*RESULTADO PRIM[AÁ]RIO GOVERNO CENTRAL\s*-\s*ACIMA",
    "resultado_nominal_governo_central":
        r"^\s*10\.\s*RESULTADO NOMINAL DO GOVERNO CENTRAL",
}


def _achar_linha(df: pd.DataFrame, padrao: str) -> int | None:
    for i in range(df.shape[0]):
        if re.search(padrao, str(df.iat[i, 0]), re.IGNORECASE):
            return i
    return None


def _mapa_colunas_mes(df: pd.DataFrame) -> tuple[int, dict[int, str]]:
    """Acha a linha de cabeçalho ('Discriminação') e mapeia coluna -> 'AAAA-MM'."""
    cab = None
    for i in range(df.shape[0]):
        if str(df.iat[i, 0]).strip().lower().startswith("discrimina"):
            cab = i
            break
    if cab is None:
        raise RuntimeError("Cabeçalho 'Discriminação' não encontrado na aba.")

    col_mes: dict[int, str] = {}
    for j in range(1, df.shape[1]):
        v = df.iat[cab, j]
        if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
            col_mes[j] = f"{v.year}-{v.month:02d}"
    return cab, col_mes


def extrair_series(xlsx_path: str | Path, desde: str = DESDE) -> list[FatoFiscal]:
    """Lê a planilha e devolve os fatos (uma linha por métrica/mês)."""
    df = pd.read_excel(xlsx_path, sheet_name=ABA, header=None)
    _, col_mes = _mapa_colunas_mes(df)

    fatos: list[FatoFiscal] = []
    for metrica, padrao in METRICAS_LINHA.items():
        li = _achar_linha(df, padrao)
        if li is None:
            print(f"[load_series] rubrica não encontrada: {metrica}")
            continue
        for j, mes in col_mes.items():
            if mes < desde:
                continue
            try:
                valor = float(df.iat[li, j])
            except (TypeError, ValueError):
                continue
            if pd.isna(valor):
                continue
            fatos.append(
                FatoFiscal(
                    mes_referencia=mes,
                    metrica=metrica,
                    valor=round(valor, 2),
                    unidade=UNIDADE,
                )
            )
    return fatos


def carregar_series(xlsx_path: str | Path, desde: str = DESDE) -> int:
    """Extrai e faz upsert da série em fatos_fiscais. Retorna nº de linhas."""
    fatos = extrair_series(xlsx_path, desde=desde)
    print(f"[load_series] {len(fatos)} fatos extraídos da planilha (desde {desde}).")
    return carregar(fatos)


if __name__ == "__main__":
    import sys

    caminho = sys.argv[1] if len(sys.argv) > 1 else "data/raw/serie.xlsx"
    for f in extrair_series(caminho)[:15]:
        print(f"  {f.mes_referencia}  {f.metrica:>36} = {f.valor:>14,.1f}")
