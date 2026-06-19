"""
extract.py
----------
PASSO 2 do pipeline: extrair o conteúdo do PDF, separando os dois mundos:

  TRACK ESTRUTURADO  -> extract_tables()  : as TABELAS de números.
  TRACK NÃO ESTRUTURADO -> extract_text() : o TEXTO corrido (justificativas).

Usamos pdfplumber porque ele preserva bem o layout de PDFs "digitais"
(gerados por software, não escaneados), que é o caso dos relatórios do
Tesouro. Para PDF escaneado precisaríamos de OCR — não é o caso aqui.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pdfplumber


def extract_text(pdf_path: str | Path) -> str:
    """Extrai todo o texto corrido do PDF, página a página."""
    partes: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, pagina in enumerate(pdf.pages, start=1):
            texto = pagina.extract_text() or ""
            if texto.strip():
                partes.append(f"[Página {i}]\n{texto}")
    return "\n\n".join(partes)


def limpar_texto(texto: str) -> str:
    """Limpeza leve: normaliza espaços e quebras de linha.

    Por quê: PDFs costumam quebrar frases no meio e deixar espaços
    duplicados. Texto mais limpo => chunks melhores => RAG mais preciso.
    """
    texto = texto.replace("\xa0", " ")          # espaço não-quebrável
    texto = re.sub(r"[ \t]+", " ", texto)        # espaços múltiplos
    texto = re.sub(r"\n{3,}", "\n\n", texto)     # excesso de linhas vazias
    return texto.strip()


def extract_tables(pdf_path: str | Path) -> list[pd.DataFrame]:
    """Extrai todas as tabelas do PDF como DataFrames do pandas.

    Cada tabela vira um DataFrame "bruto" (primeira linha = cabeçalho).
    A curadoria/normalização desses números acontece depois, em
    load_structured.py, onde validamos o schema com Pydantic.
    """
    tabelas: list[pd.DataFrame] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pagina in pdf.pages:
            for bruta in pagina.extract_tables():
                if not bruta or len(bruta) < 2:
                    continue
                cabecalho, *linhas = bruta
                cabecalho = [str(c).strip() if c else f"col_{i}"
                             for i, c in enumerate(cabecalho)]
                df = pd.DataFrame(linhas, columns=cabecalho)
                tabelas.append(df)
    return tabelas


if __name__ == "__main__":
    # Teste rápido: aponte para um PDF já baixado em data/raw/.
    import sys

    caminho = sys.argv[1] if len(sys.argv) > 1 else "data/raw/exemplo.pdf"
    print("=== TEXTO (primeiros 800 chars) ===")
    print(limpar_texto(extract_text(caminho))[:800])
    print("\n=== TABELAS ENCONTRADAS ===")
    for i, t in enumerate(extract_tables(caminho)):
        print(f"\n--- Tabela {i} ({t.shape[0]}x{t.shape[1]}) ---")
        print(t.head())
