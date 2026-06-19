"""
models.py
---------
Modelo de dados validado e a função de carga do track ESTRUTURADO.

Mantemos estas duas peças isoladas (em vez de dentro de um loader específico)
porque são o "contrato" comum de qualquer fonte de números: validar com
Pydantic e fazer upsert idempotente em `fatos_fiscais`.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator
from sqlalchemy import create_engine, text

from . import config


class FatoFiscal(BaseModel):
    """Um número curado, pronto para virar uma linha em fatos_fiscais.

    O Pydantic é nosso "porteiro": se um valor vier fora do padrão (ex.: texto
    no lugar de número), ele falha aqui — antes de poluir o banco. Isso é
    qualidade de dados na prática.
    """

    mes_referencia: str
    metrica: str
    valor: float
    unidade: str

    @field_validator("mes_referencia")
    @classmethod
    def _mes_no_formato(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}", v):
            raise ValueError("mes_referencia deve estar no formato 'AAAA-MM'")
        return v


def carregar(fatos: list[FatoFiscal]) -> int:
    """Faz upsert dos fatos em fatos_fiscais. Retorna nº de linhas gravadas.

    Idempotência: a UNIQUE(mes_referencia, metrica) + ON CONFLICT garante que
    rodar o pipeline de novo para o mesmo mês ATUALIZA os valores em vez de
    duplicar — exatamente o que queremos num pipeline que pode ser re-disparado.
    """
    if not fatos:
        print("[carregar] nada a carregar (0 fatos).")
        return 0

    engine = create_engine(config.DATABASE_URL)
    sql = text(
        """
        INSERT INTO fatos_fiscais (mes_referencia, metrica, valor, unidade)
        VALUES (:mes_referencia, :metrica, :valor, :unidade)
        ON CONFLICT (mes_referencia, metrica)
        DO UPDATE SET valor = EXCLUDED.valor,
                      unidade = EXCLUDED.unidade,
                      criado_em = now();
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, [f.model_dump() for f in fatos])
    engine.dispose()

    print(f"[carregar] {len(fatos)} fatos gravados/atualizados.")
    return len(fatos)
