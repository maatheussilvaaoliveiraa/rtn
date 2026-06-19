"""Teste rápido de conexão com o Neon. Não imprime segredos."""
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
url = os.getenv("DATABASE_URL", "")

if not url:
    print("ERRO: DATABASE_URL vazio no .env")
    sys.exit(1)
if not url.startswith("postgresql+psycopg://"):
    print("AVISO: o DATABASE_URL nao comeca com 'postgresql+psycopg://'.")
    print("       Troque o prefixo 'postgresql://' por 'postgresql+psycopg://'.")

try:
    engine = create_engine(url)
    with engine.connect() as conn:
        versao = conn.execute(text("SELECT version();")).scalar()
        print("[OK] Conexao estabelecida com o Neon.")
        print("     Postgres:", versao.split(",")[0])

        # pgvector ativo?
        ext = conn.execute(text(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector';"
        )).scalar()
        print("[OK] Extensao pgvector ATIVA." if ext
              else "[FALTA] pgvector NAO esta ativo -> rode sql/schema.sql no Neon.")

        # tabela estruturada existe?
        tab = conn.execute(text(
            "SELECT to_regclass('public.fatos_fiscais');"
        )).scalar()
        print("[OK] Tabela fatos_fiscais existe." if tab
              else "[FALTA] tabela fatos_fiscais NAO existe -> rode sql/schema.sql.")

    engine.dispose()
    print("\nTeste concluido.")
except Exception as e:
    print("[ERRO] Falha ao conectar:")
    print("      ", type(e).__name__, "-", str(e)[:300])
    sys.exit(1)
