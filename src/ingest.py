"""
ingest.py
---------
PASSO 1 do pipeline: baixar o PDF do Sumário Executivo do RTN.

Estratégia: o site do Tesouro Transparente pode mudar de layout, então
deixamos DUAS portas de entrada:
  1) RTN_PDF_URL no .env  -> baixa direto dessa URL (à prova de mudanças).
  2) scraper best-effort   -> tenta achar o link mais recente no site.

Isso é uma decisão consciente de arquitetura: scraping de site de governo
é o ponto mais frágil do pipeline, então isolamos esse risco aqui e damos
um "plano B" manual.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import config

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (pipeline-rtn; estudo/portfolio)"}


def _descobrir_url() -> str:
    """Tenta localizar a URL do PDF mais recente.

    OBS: a busca exata depende do HTML atual do Tesouro. Mantemos um
    seletor genérico (qualquer link .pdf que cite 'RTN' ou 'Resultado')
    e documentamos que, se o site mudar, basta setar RTN_PDF_URL no .env.
    """
    if config.RTN_PDF_URL:
        return config.RTN_PDF_URL

    # Página de publicações do RTN (ajuste a rota se o site mudar).
    pagina = f"{config.TESOURO_BASE}/publicacoes/resultado-do-tesouro-nacional-rtn/"
    resp = requests.get(pagina, headers=HEADERS, timeout=60)
    resp.raise_for_status()

    sopa = BeautifulSoup(resp.text, "html.parser")
    candidatos = []
    for a in sopa.find_all("a", href=True):
        href = a["href"]
        texto = (a.get_text() or "").lower()
        if href.lower().endswith(".pdf") and (
            "sum" in texto or "rtn" in texto or "resultado" in texto
        ):
            url = href if href.startswith("http") else config.TESOURO_BASE + href
            candidatos.append(url)

    if not candidatos:
        raise RuntimeError(
            "Não encontrei o PDF no site. Defina RTN_PDF_URL no .env "
            "com o link direto do Sumário Executivo do mês."
        )
    # Heurística simples: o primeiro costuma ser o mais recente.
    return candidatos[0]


def baixar_pdf(mes_referencia: str | None = None) -> Path:
    """Baixa o PDF e devolve o caminho local.

    mes_referencia: rótulo 'AAAA-MM' usado para nomear o arquivo e como
    chave de versionamento dos dados. Se None, usa o mês corrente.
    """
    if mes_referencia is None:
        hoje = dt.date.today()
        mes_referencia = f"{hoje.year}-{hoje.month:02d}"

    url = _descobrir_url()
    destino = RAW_DIR / f"rtn_{mes_referencia}.pdf"

    print(f"[ingest] Baixando: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    destino.write_bytes(resp.content)
    print(f"[ingest] Salvo em: {destino} ({len(resp.content) // 1024} KB)")
    return destino


if __name__ == "__main__":
    baixar_pdf()
