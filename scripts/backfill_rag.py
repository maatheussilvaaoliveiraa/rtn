"""
backfill_rag.py
---------------
Indexa o TEXTO (RAG) de vários meses de Sumários Executivos de uma vez, para
que o chat cubra o histórico — não só o último mês.

Uso:
    python scripts/backfill_rag.py 2024-05 2026-04

O track estruturado (números do dashboard) NÃO precisa de backfill: a planilha
de série histórica já é cumulativa e é carregada inteira pelo pipeline.

Cada mês é independente: se um PDF não existir/baixar, apenas pulamos e
seguimos. A indexação é idempotente por mês (reprocessar não duplica).
"""

from __future__ import annotations

import sys
from pathlib import Path

# permite rodar como "python scripts/backfill_rag.py" (raiz no sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.extract import extract_text, limpar_texto  # noqa: E402
from src.ingest import baixar_pdf  # noqa: E402
from src.rag_index import indexar  # noqa: E402


def _meses(inicio: str, fim: str) -> list[str]:
    ai, mi = int(inicio[:4]), int(inicio[5:7])
    af, mf = int(fim[:4]), int(fim[5:7])
    out = []
    a, m = ai, mi
    while (a, m) <= (af, mf):
        out.append(f"{a}-{m:02d}")
        m += 1
        if m > 12:
            a, m = a + 1, 1
    return out


def main() -> None:
    inicio = sys.argv[1] if len(sys.argv) > 1 else "2024-05"
    fim = sys.argv[2] if len(sys.argv) > 2 else "2026-04"
    config.validar_config()
    # Garante uso do resolver automático (ignora um RTN_PDF_URL fixo de mês).
    config.RTN_PDF_URL = ""

    ok, falhas = 0, []
    for mes in _meses(inicio, fim):
        try:
            pdf = baixar_pdf(mes)
            texto = limpar_texto(extract_text(pdf))
            n = indexar(texto, mes)
            print(f"[backfill] {mes}: {n} chunks OK")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[backfill] {mes}: PULADO ({type(e).__name__}: {str(e)[:80]})")
            falhas.append(mes)

    print(f"\n[backfill] concluído: {ok} meses indexados, {len(falhas)} pulados.")
    if falhas:
        print(f"[backfill] pulados: {', '.join(falhas)}")


if __name__ == "__main__":
    main()
