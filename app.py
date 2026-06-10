import os
import logging

import gradio as gr

from embeddings import get_collection, build_index, CHUNKS_PATH
from retriever import Retriever,MetadataFilter
from generator import generate_response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ingestion — runs once on startup
# ---------------------------------------------------------------------------

def run_ingestion():
    collection = get_collection()
    if collection.count() > 0:
        print(f"Vector store already populated ({collection.count()} chunks). Skipping ingestion.")
        print("To re-ingest, delete the ./chroma_db folder and restart.")
        return
    if not os.path.exists(CHUNKS_PATH):
        print(f"\n⚠️  {CHUNKS_PATH} not found.\nRun `python ingest_pipeline.py` first.\n")
        return
    print("Embedding chunks into the vector store...")
    collection = build_index(reset=False)
    print(f"Ingestion complete. {collection.count()} chunks stored.")


# ---------------------------------------------------------------------------
# Retriever + memory (one per session)
# ---------------------------------------------------------------------------

_retriever = None
memory = None

def get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


# ---------------------------------------------------------------------------
# Chat handler
# ---------------------------------------------------------------------------

def chat(message, history, source_filter, date_from, date_to):


    if not message.strip():
        return ""

    retriever = get_retriever()
    
    # filters = MetadataFilter(
    #     sources=source_filter or [],
    #     date_gte=date_from or None,
    #     date_lte=date_to or None,
    # ).to_where()

    # logger.info("Filters: %s", filters)
    retrieved = retriever.semantic_search(message)

    return generate_response(
        query=message,          
        retrieved_chunks=retrieved,
    )



# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

with gr.Blocks(
    theme=gr.themes.Soft(primary_hue="blue"),
    title="The Unofficial Immigration Guide",
    css="""
        .gradio-container { max-width: 860px !important; margin: 0 auto !important; }
        footer { display: none !important; }
    """
    ) as guide:

    gr.HTML("""
        <div style="text-align:center; padding:1.25rem 0 0.5rem;">
            <h1 style="font-size:2rem; font-weight:700; color:#312e81; margin:0;">
                🛂 The Unofficial Immigration Guide
            </h1>
            <p style="color:#6b7280; font-size:1rem; margin:0.4rem 0 0;">
                Ask anything about US immigration — answers grounded in community
                experience, with sources cited.
            </p>
        </div>
    """)

    gr.ChatInterface(
        fn=chat,
        type="messages",
        chatbot=gr.Chatbot(
            height=480,
            type="messages",
            placeholder=(
                "<div style='text-align:center; color:#9ca3af; margin-top:3rem;'>"
                "Ask an immigration question to get started"
                "</div>"
            ),
        ),
        examples=[
            "What documents do I need for a greencard if I'm married to a US citizen but live abroad?",
            "How long does premium processing take for J1 visas and how much does it cost?",
            "Am I eligible for the H1B Masters quota with a STEM degree?",
            "My H4 EAD shows mailed but I never received it. What do I do?",
            "My F1 visa was rejected and classes start in a month. How do I reapply?",
        ],
        cache_examples=False,
    )   


if __name__ == "__main__":
    print("\n" + "="*50)
    print("  The Unofficial Immigration Guide — loading")
    print("="*50 + "\n")
    run_ingestion()
    guide.launch()