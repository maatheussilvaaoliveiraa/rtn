"""
load_structured.py
------------------
PASSO 4 do pipeline (track ESTRUTURADO): pegar os números do relatório e
gravá-los, já limpos e validados, na tabela `fatos_fiscais` do Neon.

Por que esta etapa existe separada do extract.py?
  - extract.py só "puxa" o conteúdo bruto (texto + tabelas pandas).
  - aqui fazemos a CURADORIA: identificar QUAIS números nos interessam,
    converter o formato brasileiro (1.234,56) para float, anexar a unidade
    e VALIDAR cada registro com Pydantic antes de tocar no banco.

Decisão de arquitetura: extraímos as métricas a partir do TEXTO corrido,
não das tabelas. Tabelas de PDF de governo quebram de formas imprevisíveis
(células mescladas, colunas deslocadas); já o texto do "Sumário Executivo"
enuncia os números-chave em frases ("apresentou um superávit primário de
R$ 25,2 bilhões"). Buscar por frase + número é mais robusto. Se o layout
mudar, basta ajustar os padrões em METRICAS — um único ponto de manutenção.

O QUE capturamos: o Sumário Executivo é narrativo. Ele só traz valores
ABSOLUTOS para os SALDOS primários (resultados); receita e despesa aparecem
apenas como variação ano-a-ano (+R$ X bilhões), e os níveis absolutos delas
vivem nas "Tabelas Anexas" (outro arquivo). Por isso o track estruturado
modela exatamente os saldos que o relatório afirma como valor absoluto, em
R$ bilhões, com SINAL derivado de "superávit" (+) ou "déficit" (-).
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, field_validator
from sqlalchemy import create_engine, text

from . import config


# Grupo regex de um número em R$ no texto (ex.: "R$ 25,2", "R$ 1.234,5").
# Fica entre parênteses nomeados quando embutido nos padrões abaixo.
_NUM = r"R\$\s*-?\d{1,3}(?:\.\d{3})*(?:,\d+)?"

# Palavras que indicam SINAL do saldo. "superávit/superavitário" => positivo;
# "déficit/deficitário" => negativo (um déficit é um resultado primário < 0).
_SINAL = r"super[aá]vit[aá]?r?i?o?|d[eé]ficit[aá]?r?i?o?"


# ---------------------------------------------------------------------------
# Registro das métricas (SALDOS primários, em R$ bilhões).
#   Cada padrão tem dois grupos nomeados:
#     (?P<sinal>...)  -> a palavra superávit/déficit que define o sinal.
#     (?P<valor>...)  -> o número em R$.
#   Manter isso como dados (não como código espalhado) facilita revisar e
#   estender. Os padrões toleram acentuação/caixa e pequenas variações de
#   redação ("foi superavitário em", "registraram um superávit de").
# ---------------------------------------------------------------------------
METRICAS: dict[str, dict] = {
    # Resultado primário do Governo Central no mês.
    "resultado_primario_governo_central": {
        "padrao": r"Governo Central apresentou um (?P<sinal>" + _SINAL
        + r")\s+prim[aá]rio de (?P<valor>" + _NUM + r")",
        "unidade": "R$ bilhões",
    },
    # Resultado consolidado Tesouro Nacional + Banco Central no mês.
    "resultado_tesouro_bc": {
        "padrao": r"Tesouro Nacional e do Banco Central foi (?P<sinal>" + _SINAL
        + r")\s+em (?P<valor>" + _NUM + r")",
        "unidade": "R$ bilhões",
    },
    # Resultado da Previdência Social (RGPS) no mês.
    "resultado_rgps": {
        "padrao": r"\(RGPS\).{0,40}?(?P<sinal>" + _SINAL
        + r") de (?P<valor>" + _NUM + r")",
        "unidade": "R$ bilhões",
    },
    # Resultado primário do Governo Central acumulado no ano (YTD).
    "resultado_primario_gov_central_acumulado": {
        "padrao": r"Governo Central acumulado.{0,80}?(?P<sinal>" + _SINAL
        + r") de (?P<valor>" + _NUM + r")",
        "unidade": "R$ bilhões",
    },
    # Resultado consolidado Tesouro + BC acumulado no ano (YTD).
    "resultado_tesouro_bc_acumulado": {
        "padrao": r"Tesouro Nacional e o Banco Central registraram um (?P<sinal>"
        + _SINAL + r") de (?P<valor>" + _NUM + r")",
        "unidade": "R$ bilhões",
    },
}


def parse_valor_br(bruto: str) -> Optional[float]:
    """Converte um número em formato brasileiro para float.

    Regras tratadas:
      - separador de milhar '.' e decimal ',' -> formato Python.
      - parênteses indicam valor negativo (convenção contábil).
      - símbolos 'R$', espaços e '%' são descartados.
    Retorna None se não sobrar um número parseável.
    """
    if bruto is None:
        return None
    s = bruto.strip()
    negativo = "(" in s and ")" in s  # convenção contábil de negativo
    s = s.replace("R$", "").replace("%", "")
    s = s.replace("(", "").replace(")", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".")  # milhar -> _, decimal -> .
    if s.startswith("-"):
        negativo = True
        s = s[1:]
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    valor = float(s)
    return -valor if negativo else valor


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


def _sinal_negativo(palavra: str) -> bool:
    """True se a palavra-sinal indica déficit (resultado primário negativo)."""
    return bool(re.search(r"d[eé]ficit", palavra, re.IGNORECASE))


def extrair_fatos(texto: str, mes_referencia: str) -> list[FatoFiscal]:
    """Varre o texto e devolve os saldos primários encontrados.

    Para cada métrica, casa a frase-manchete correspondente, lê o número e
    aplica o sinal a partir de "superávit"/"déficit". Métrica ausente no mês
    é apenas avisada (o relatório pode não citar todos os saldos todo mês).
    """
    fatos: list[FatoFiscal] = []

    for metrica, cfg in METRICAS.items():
        m = re.search(cfg["padrao"], texto, re.IGNORECASE | re.DOTALL)
        if not m:
            print(f"[load_structured] métrica não encontrada no texto: {metrica}")
            continue

        valor = parse_valor_br(m.group("valor"))
        if valor is None:
            print(f"[load_structured] número ilegível para {metrica}: "
                  f"{m.group('valor')!r}")
            continue
        if _sinal_negativo(m.group("sinal")):
            valor = -abs(valor)

        try:
            fatos.append(
                FatoFiscal(
                    mes_referencia=mes_referencia,
                    metrica=metrica,
                    valor=valor,
                    unidade=cfg["unidade"],
                )
            )
        except Exception as e:  # noqa: BLE001 — validação Pydantic
            print(f"[load_structured] descartado {metrica} (inválido): {e}")

    return fatos


def carregar(fatos: list[FatoFiscal]) -> int:
    """Faz upsert dos fatos em fatos_fiscais. Retorna nº de linhas gravadas.

    Idempotência: a UNIQUE(mes_referencia, metrica) + ON CONFLICT garante que
    rodar o pipeline de novo para o mesmo mês ATUALIZA os valores em vez de
    duplicar — exatamente o que queremos num pipeline que pode ser re-disparado.
    """
    if not fatos:
        print("[load_structured] nada a carregar (0 fatos).")
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

    print(f"[load_structured] {len(fatos)} fatos gravados/atualizados.")
    return len(fatos)


def processar(texto: str, mes_referencia: str) -> int:
    """Atalho usado pelo orquestrador: extrai e carrega numa tacada."""
    fatos = extrair_fatos(texto, mes_referencia)
    return carregar(fatos)


if __name__ == "__main__":
    # Teste isolado: lê um PDF já baixado, extrai o texto e tenta capturar
    # as métricas (sem gravar no banco, só imprime o que achou).
    import sys

    from .extract import extract_text, limpar_texto

    caminho = sys.argv[1] if len(sys.argv) > 1 else "data/raw/exemplo.pdf"
    txt = limpar_texto(extract_text(caminho))
    for f in extrair_fatos(txt, "2026-04"):
        print(f"  {f.metrica:>42} = {f.valor:>8,.1f}  {f.unidade}")
