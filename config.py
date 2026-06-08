import os
from dotenv import load_dotenv

load_dotenv()

# --- LLM ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "llama-3.3-70b-versatile"

# --- Embeddings ---
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
UTILITY_MODEL = "llama-3.1-8b-instant"

# --- Vector store ---
CHROMA_COLLECTION = "The_Unofficial_Guide"
CHROMA_PATH = "./chroma_db"

# --- Retrieval ---
N_RESULTS = 5

# --- Documents ---
DOCS_PATH = "./documents"
