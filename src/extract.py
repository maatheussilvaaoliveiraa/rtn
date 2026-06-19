"""
extract.py
----------
Extrai o TEXTO corrido do PDF do Sumário Executivo, insumo do track RAG.

Usamos pdfplumber porque ele preserva bem o layout de PDFs "digitais"
(gerados por software, não escaneados), que é o caso dos relatórios do
Tesouro. Para PDF escaneado precisaríamos de OCR — não é o caso aqui.

(Os números do dashboard NÃO vêm do PDF: o track estruturado usa a planilha
oficial de série histórica — ver load_series.py.)
"""

from __future__ import annotations

import re
from pathlib import Path

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


if __name__ == "__main__":
    # Teste rápido: aponte para um PDF já baixado em data/raw/.
    import sys

    caminho = sys.argv[1] if len(sys.argv) > 1 else "data/raw/exemplo.pdf"
    print("=== TEXTO (primeiros 800 chars) ===")
    print(limpar_texto(extract_text(caminho))[:800])
