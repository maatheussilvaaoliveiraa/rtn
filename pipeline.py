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
from src.ingest import baixar_pdf
from src.load_structured import processar as carregar_numeros
from src.rag_index import indexar


def _mes_default() -> str:
    """Mês de referência padrão = mês corrente, no formato 'AAAA-MM'."""
    hoje = dt.date.today()
    return f"{hoje.year}-{hoje.month:02d}"


def rodar(mes_referencia: str) -> int:
    """Executa o pipeline completo para um mês. Retorna código de saída (0=ok)."""
    print(f"\n=== PIPELINE RTN — mês de referência: {mes_referencia} ===\n")
    config.validar_config()  # falha cedo se faltar DATABASE_URL/GROQ_API_KEY

    # --- Etapa 1: baixar o PDF ---
    pdf_path = baixar_pdf(mes_referencia)

    # --- Etapa 2: extrair e limpar o texto (insumo dos dois tracks) ---
    texto = limpar_texto(extract_text(pdf_path))
    print(f"[pipeline] texto extraído: {len(texto):,} caracteres.")

    ok_numeros = ok_texto = False

    # --- Etapa 3: track estruturado (números -> fatos_fiscais) ---
    try:
        n = carregar_numeros(texto, mes_referencia)
        ok_numeros = n > 0
        print(f"[pipeline] track estruturado: {n} métricas.")
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] FALHA no track estruturado: {type(e).__name__}: {e}")

    # --- Etapa 4: track não estruturado (texto -> pgvector) ---
    try:
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
