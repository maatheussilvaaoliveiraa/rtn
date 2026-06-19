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


def _pagina_publicacao(ano: int, mes: int) -> str:
    """URL da página mensal do RTN. Obs.: o mês vai SEM zero à esquerda."""
    return (
        f"{config.TESOURO_BASE}/publicacoes/"
        f"boletim-resultado-do-tesouro-nacional-rtn/{ano}/{mes}"
    )


def _resolver_url_cdn(anexo_url: str) -> str:
    """O link '/publicacao-anexo/NNNNN' é um wrapper HTML com um <iframe> que
    aponta para o PDF real no CDN. Aqui seguimos esse iframe e devolvemos a
    URL direta do PDF (que o requests consegue baixar)."""
    resp = requests.get(anexo_url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    sopa = BeautifulSoup(resp.text, "html.parser")
    iframe = sopa.find("iframe", src=True)
    if iframe and iframe["src"].lower().endswith(".pdf"):
        return iframe["src"]
    # Se o servidor já devolveu o PDF direto (sem wrapper), use a própria URL.
    if resp.headers.get("content-type", "").lower().startswith("application/pdf"):
        return anexo_url
    raise RuntimeError(f"Não achei o PDF dentro de {anexo_url}.")


def _achar_anexo(ano: int, mes: int, chave_texto: str, rotulo: str) -> str:
    """Abre a página mensal e devolve o link '/publicacao-anexo/...' cujo texto
    contém `chave_texto` (ex.: 'sumario_executivo' ou 'serie_historica')."""
    pagina = _pagina_publicacao(ano, mes)
    resp = requests.get(pagina, headers=HEADERS, timeout=60)
    resp.raise_for_status()

    sopa = BeautifulSoup(resp.text, "html.parser")
    for a in sopa.find_all("a", href=True):
        texto = (a.get_text() or "").lower()
        if "publicacao-anexo" in a["href"] and chave_texto in texto:
            return a["href"]

    raise RuntimeError(
        f"Não encontrei o '{rotulo}' na página {pagina}. O relatório do mês "
        "pode não ter sido publicado, ou o site mudou de layout."
    )


def _descobrir_url(ano: int, mes: int) -> str:
    """Resolve a URL do PDF do Sumário Executivo para um ano/mês.

    Estratégia: achar a âncora do 'Sumário Executivo' na página mensal e seguir
    o iframe até o PDF real no CDN. Se RTN_PDF_URL estiver setado, ele tem
    prioridade (override manual, à prova de mudanças no site).
    """
    if config.RTN_PDF_URL:
        return config.RTN_PDF_URL
    anexo = _achar_anexo(ano, mes, "sumario_executivo", "Sumário Executivo")
    return _resolver_url_cdn(anexo)


def baixar_pdf(mes_referencia: str | None = None) -> Path:
    """Baixa o PDF e devolve o caminho local.

    mes_referencia: rótulo 'AAAA-MM' usado para nomear o arquivo e como
    chave de versionamento dos dados. Se None, usa o mês corrente.
    """
    if mes_referencia is None:
        hoje = dt.date.today()
        mes_referencia = f"{hoje.year}-{hoje.month:02d}"

    ano, mes = int(mes_referencia[:4]), int(mes_referencia[5:7])
    url = _descobrir_url(ano, mes)
    destino = RAW_DIR / f"rtn_{mes_referencia}.pdf"

    print(f"[ingest] Baixando PDF: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    destino.write_bytes(resp.content)
    print(f"[ingest] Salvo em: {destino} ({len(resp.content) // 1024} KB)")
    return destino


def baixar_serie_historica(mes_referencia: str | None = None) -> Path:
    """Baixa a planilha 'série histórica' (.xlsx) do RTN e devolve o caminho.

    Diferente do Sumário Executivo (PDF), o link da série histórica aponta
    direto para o .xlsx (sem wrapper iframe). A planilha é CUMULATIVA: a edição
    de qualquer mês contém toda a série desde 1997, então normalmente basta a
    mais recente para alimentar todo o track estruturado.
    """
    if mes_referencia is None:
        hoje = dt.date.today()
        mes_referencia = f"{hoje.year}-{hoje.month:02d}"

    ano, mes = int(mes_referencia[:4]), int(mes_referencia[5:7])
    anexo = _achar_anexo(ano, mes, "serie_historica", "Série Histórica")
    destino = RAW_DIR / f"serie_historica_{mes_referencia}.xlsx"

    print(f"[ingest] Baixando série histórica: {anexo}")
    resp = requests.get(anexo, headers=HEADERS, timeout=180)
    resp.raise_for_status()
    destino.write_bytes(resp.content)
    print(f"[ingest] Salvo em: {destino} ({len(resp.content) // 1024} KB)")
    return destino


if __name__ == "__main__":
    baixar_pdf()
