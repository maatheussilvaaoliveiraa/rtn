"""
config.py
---------
Centraliza TODAS as configurações do projeto em um único lugar.

Por quê: em vez de espalhar strings de conexão e nomes de modelo pelo
código, lemos tudo de variáveis de ambiente (.env localmente, Secrets
em produção). Isso é boa prática de engenharia e evita vazar segredos.
"""

import os
import sys

from dotenv import load_dotenv

# Carrega o .env quando rodando localmente. Em produção as variáveis já
# existem no ambiente, e o load_dotenv simplesmente não faz nada.
load_dotenv()

# No Windows, o cache do huggingface_hub (usado pelo fastembed) tenta criar
# symlinks, o que exige Modo de Desenvolvedor/admin e gera erro ruidoso
# (WinError 1314). Em Linux (Actions/Streamlit Cloud) não há problema. Aqui
# desativamos os symlinks para que ele copie os arquivos — funciona igual.
if sys.platform == "win32":
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# --- Banco de dados ---
DATABASE_URL = os.getenv("DATABASE_URL", "")

# --- LLM (Groq) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Modelo da Groq usado na geração de respostas do RAG.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Embeddings (rodam localmente, via fastembed/ONNX) ---
# Modelo multilíngue (entende português) e leve o bastante para o free
# tier do Streamlit. Gera vetores de 384 dimensões.
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBEDDING_DIM = 384

# --- Chunking (quebra do texto para o RAG) ---
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

# --- Vector store (tabela gerenciada pelo langchain-postgres) ---
VECTOR_COLLECTION = "rtn_chunks"

# --- Ingestão ---
RTN_PDF_URL = os.getenv("RTN_PDF_URL", "")  # override manual opcional
TESOURO_BASE = "https://www.tesourotransparente.gov.br"


def validar_config() -> None:
    """Falha cedo e com mensagem clara se faltar algo essencial."""
    faltando = []
    if not DATABASE_URL:
        faltando.append("DATABASE_URL")
    if not GROQ_API_KEY:
        faltando.append("GROQ_API_KEY")
    if faltando:
        raise RuntimeError(
            "Variáveis de ambiente faltando: "
            + ", ".join(faltando)
            + ". Configure no .env (local) ou nos Secrets (produção)."
        )
