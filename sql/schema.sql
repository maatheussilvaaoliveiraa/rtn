-- =====================================================================
-- schema.sql — execute UMA VEZ no seu banco Neon (SQL editor do painel).
-- =====================================================================

-- 1) Habilita a extensão de busca vetorial.
--    As tabelas do vetor (langchain_pg_embedding / _collection) são
--    criadas automaticamente pelo langchain-postgres no primeiro run.
CREATE EXTENSION IF NOT EXISTS vector;

-- 2) Tabela do TRACK ESTRUTURADO (os números do dashboard).
--    Modelo "long/tidy": cada linha é uma métrica de um mês. Esse formato
--    é ótimo para gráficos (Plotly) e séries temporais.
CREATE TABLE IF NOT EXISTS fatos_fiscais (
    id              BIGSERIAL PRIMARY KEY,
    mes_referencia  TEXT        NOT NULL,   -- 'AAAA-MM'
    metrica         TEXT        NOT NULL,   -- ex.: 'resultado_primario'
    valor           NUMERIC,                -- valor numérico já limpo
    unidade         TEXT,                   -- ex.: 'R$ milhões', '% PIB'
    criado_em       TIMESTAMPTZ DEFAULT now(),
    UNIQUE (mes_referencia, metrica)        -- evita duplicar a mesma métrica/mês
);

CREATE INDEX IF NOT EXISTS idx_fatos_mes ON fatos_fiscais (mes_referencia);
