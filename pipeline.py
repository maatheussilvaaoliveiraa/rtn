"""
pipeline.py
-----------
ORQUESTRADOR do projeto: roda os dois fluxos na ordem certa, do Tesouro ao banco.

    ESTRUTURADO: ingest (xlsx) -> load_series -> fatos_fiscais (números).
    RAG:         ingest (pdf)  -> extract -> rag_index -> pgvector (texto/chat).

É este arquivo que o GitHub Actions executa diariamente. Também dá para rodar
na mão:  python pipeline.py --mes 2026-04  (ou sem --mes p/ o mês mais recente).

Decisão: os dois "tracks" (números e texto) são independentes. Se um falhar,
o outro ainda agrega valor — então cada um é envolvido em seu próprio try,
e no fim reportamos um resumo. Mas se NADA funcionou, saímos com erro (para
o Actions marcar o job como vermelho e o usuário ser avisado).
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text

from src import config
from src.extract import extract_text, limpar_texto
from src.ingest import baixar_pdf, baixar_serie_historica, mes_mais_recente_publicado
from src.load_series import carregar_series
from src.rag_index import indexar


def _ja_indexado(mes_referencia: str) -> bool:
    """True se o mês já tem chunks no pgvector (evita re-embeddar à toa).

    Importante para o agendamento DIÁRIO: na maioria dos dias o último mês já
    está indexado, então pulamos a etapa cara de embeddings e o run fica leve.
    """
    try:
        engine = create_engine(config.DATABASE_URL)
        with engine.connect() as conn:
            n = conn.execute(
                text(
                    "SELECT count(*) FROM langchain_pg_embedding "
                    "WHERE cmetadata->>'mes_referencia' = :mes"
                ),
                {"mes": mes_referencia},
            ).scalar()
        engine.dispose()
        return bool(n)
    except Exception:  # noqa: BLE001 — tabela ainda não existe no 1º run
        return False


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
    # Sempre rodamos: a planilha é cumulativa e pode trazer revisões de meses
    # anteriores; o upsert é idempotente.
    try:
        xlsx_path = baixar_serie_historica(mes_referencia)
        n = carregar_series(xlsx_path)
        ok_numeros = n > 0
        print(f"[pipeline] track estruturado: {n} fatos (série histórica).")
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] FALHA no track estruturado: {type(e).__name__}: {e}")

    # --- Track RAG: texto do PDF do mês -> pgvector ---
    if _ja_indexado(mes_referencia):
        ok_texto = True
        print(f"[pipeline] track RAG: {mes_referencia} já indexado — pulando.")
    else:
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
    parser = argparse.ArgumentParser(description="Pipeline RTN (Tesouro -> Neon).")
    parser.add_argument(
        "--mes",
        default=None,
        help="Mês de referência AAAA-MM. Se omitido, usa o mês PUBLICADO mais "
             "recente (ideal para o agendamento diário).",
    )
    args = parser.parse_args()

    mes = args.mes
    if mes is None:
        mes = mes_mais_recente_publicado()
        if mes is None:
            print("[pipeline] Nenhum mês publicado encontrado nas últimas "
                  "edições — nada a fazer hoje.")
            sys.exit(0)  # cron diário: ausência de novidade não é erro
        print(f"[pipeline] Mês publicado mais recente detectado: {mes}")

    sys.exit(rodar(mes))


if __name__ == "__main__":
    main()
