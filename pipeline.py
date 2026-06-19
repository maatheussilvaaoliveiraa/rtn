"""
pipeline.py
-----------
ORQUESTRADOR do projeto: roda todas as etapas na ordem certa, do PDF ao banco.

    1. ingest          -> baixa o PDF do mês.
    2. extract         -> separa texto (não estruturado) e prepara o conteúdo.
    3. load_structured -> curamos os números e gravamos em fatos_fiscais.
    4. rag_index       -> chunk + embeddings + pgvector (base do chat).

É este arquivo que o GitHub Actions executa todo mês. Também dá para rodar
na mão:  python pipeline.py --mes 2024-05

Decisão: os dois "tracks" (números e texto) são independentes. Se um falhar,
o outro ainda agrega valor — então cada um é envolvido em seu próprio try,
e no fim reportamos um resumo. Mas se NADA funcionou, saímos com erro (para
o Actions marcar o job como vermelho e o usuário ser avisado).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from src import config
from src.extract import extract_text, limpar_texto
from src.ingest import baixar_pdf, baixar_serie_historica
from src.load_series import carregar_series
from src.rag_index import indexar


def _mes_default() -> str:
    """Mês de referência padrão = mês corrente, no formato 'AAAA-MM'."""
    hoje = dt.date.today()
    return f"{hoje.year}-{hoje.month:02d}"


def rodar(mes_referencia: str) -> int:
    """Executa o pipeline completo para um mês. Retorna código de saída (0=ok).

    Dois tracks independentes e de fontes diferentes:
      - ESTRUTURADO: planilha de série histórica (.xlsx) -> fatos_fiscais.
        A planilha é cumulativa, então uma execução atualiza toda a série.
      - RAG: texto do Sumário Executivo (PDF) do mês -> pgvector (base do chat).
    """
    print(f"\n=== PIPELINE RTN — mês de referência: {mes_referencia} ===\n")
    config.validar_config()  # falha cedo se faltar DATABASE_URL/GROQ_API_KEY

    ok_numeros = ok_texto = False

    # --- Track estruturado: série histórica (xlsx) -> fatos_fiscais ---
    try:
        xlsx_path = baixar_serie_historica(mes_referencia)
        n = carregar_series(xlsx_path)
        ok_numeros = n > 0
        print(f"[pipeline] track estruturado: {n} fatos (série histórica).")
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] FALHA no track estruturado: {type(e).__name__}: {e}")

    # --- Track RAG: texto do PDF do mês -> pgvector ---
    try:
        pdf_path = baixar_pdf(mes_referencia)
        texto = limpar_texto(extract_text(pdf_path))
        print(f"[pipeline] texto extraído: {len(texto):,} caracteres.")
        c = indexar(texto, mes_referencia)
        ok_texto = c > 0
        print(f"[pipeline] track RAG: {c} chunks indexados.")
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] FALHA no track RAG: {type(e).__name__}: {e}")

    # --- Resumo ---
    print("\n=== RESUMO ===")
    print(f"  números (fatos_fiscais): {'OK' if ok_numeros else 'FALHOU'}")
    print(f"  texto (RAG/pgvector):    {'OK' if ok_texto else 'FALHOU'}")

    if not (ok_numeros or ok_texto):
        print("\n[pipeline] Nada foi gravado — encerrando com erro.")
        return 1
    print("\n[pipeline] Concluído.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline RTN (PDF -> Neon).")
    parser.add_argument(
        "--mes",
        default=_mes_default(),
        help="Mês de referência no formato AAAA-MM (padrão: mês atual).",
    )
    args = parser.parse_args()
    sys.exit(rodar(args.mes))


if __name__ == "__main__":
    main()
