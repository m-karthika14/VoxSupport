# src/module1_basic_rag.py
from langchain_community.retrievers import BM25Retriever
from sentence_transformers import CrossEncoder
import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

# 1. Load PDF
#pdf_path = r"D:\articence\voice_rag\zero_latency_voice_kb\data\hp_troubleshooting_guide.pdf"
pdf_path = r"D:\articence\voice_rag\zero_latency_voice_kb\data\airbus.pdf"
loader = PyPDFLoader(pdf_path)
docs = loader.load()

print(f"Loaded {len(docs)} pages.")

# 2. Split into chunks
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
)
splits = text_splitter.split_documents(docs)

print(f"Split into {len(splits)} chunks.")

# 3. Create vectorstore (FAISS) - GPU accelerated
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={'device': 'cpu'}  # Use 'cuda' if GPU fixed
)

vectorstore = FAISS.from_documents(splits, embeddings)
retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
print("Vectorstore ready.")

# BM25 retriever (lexical)
bm25_retriever = BM25Retriever.from_documents(splits)
bm25_retriever.k = 4
print("BM25 retriever ready.")

def hybrid_retrieve(query, k=4):
    """Hybrid search: BM25 + FAISS"""
    dense_docs = retriever.invoke(query)
    sparse_docs = bm25_retriever.invoke(query)
    
    # Combine and de-duplicate
    seen = set()
    combined = []
    for d in dense_docs + sparse_docs:
        key = d.page_content
        if key not in seen:
            seen.add(key)
            combined.append(d)
    
    return combined[:2 * k]

# Cross-Encoder reranker - GPU accelerated
reranker_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
print("Reranker model loaded.")

def rerank_docs(query, docs, top_k=4):
    """Rerank with Cross-Encoder for precision"""
    if not docs:
        return []
    pairs = [(query, d.page_content) for d in docs]
    scores = reranker_model.predict(pairs)
    scored = list(zip(docs, scores))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [d for d, s in scored[:top_k]]

# Fast vs Heavy retrievers
def fast_retriever(query, k=4):
    """Fast hybrid (no rerank) for pre-fetch"""
    docs = hybrid_retrieve(query, k=k)
    return docs[:k]

def heavy_retrieve(query, k=4):
    """Heavy hybrid + rerank for final answer"""
    initial_docs = hybrid_retrieve(query, k=2 * k)
    return rerank_docs(query, initial_docs, top_k=k)

# 4. LLM
llm = ChatOllama(
    model="phi3",
    temperature=0.3,
)

# 5. Prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", 
     """You are a hardware support agent. Answer using ONLY the context.
     The context ALWAYS contains relevant info. Give short to the point answers. Do NOT say "no info" or "context doesn't contain".
     If truly unclear, say "Check page X of the manual".
     Be concise, technical, step-by-step."""),
    ("human", "Context:\n{context}\n\nQuestion: {question}"),
])


# 6. RAG chain (heavy retrieval)
def format_docs(docs):
    return "\n\n".join(d.page_content for d in docs)

def retrieve_and_format(query):
    docs = heavy_retrieve(query, k=4)
    return format_docs(docs)

rag_chain = (
    {"context": RunnablePassthrough() | retrieve_and_format,
     "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

# 🎯 TASK C: VOICE-OPTIMIZED POST-PROCESSING
def spoken_english_post_process(text, return_chunks=True):
    # 1) Build short sentences
    sentences = text.replace("\n", " ").split(".")
    chunks = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        words = sent.split()
        if len(words) > 12:
            for i in range(0, len(words), 10):
                chunks.append(" ".join(words[i:i+10]).strip())
        else:
            chunks.append(sent)

    # 2) Phonetic technical terms
    tech_terms = {
        "RAM": "R-A-M", "BIOS": "B-I-O-S", "CPU": "C-P-U", "GPU": "G-P-U",
        "SSD": "S-S-D", "HDD": "H-D-D", "PCIe": "P-C-I-E", "NVMe": "N-V-M-E",
        "UEFI": "U-E-F-I", "CMOS": "C-M-O-S", "POST": "P-O-S-T", "PSU": "P-S-U",
    }

    # 3) Casual replacements
    casual_map = {
        "therefore": "so", "however": "but", "try to": "try", "attempt to": "try",
        "it is": "it's", "there is": "there's", "do not": "don't", "cannot": "can't",
    }

    def normalize(s: str) -> str:
        for term, phon in tech_terms.items():
            s = s.replace(term, phon)
        for formal, casual in casual_map.items():
            s = s.replace(formal, casual)
        return s.strip()

    chunks = [normalize(c) for c in chunks if normalize(c)]

    if return_chunks:
        return chunks
    return ". ".join(chunks) + "."


# Export for Module 3
rag_chain, fast_retriever = rag_chain, fast_retriever
spoken_english_post_process  # Export post-processor

# Test
if __name__ == "__main__":
    question = "How do I troubleshoot a PC that won't boot?"
    print("\nQuestion:", question)
    print("Retrieving and generating answer...\n")
    
    response = rag_chain.invoke(question)
    print("Raw LLM answer:\n", response)
    
    spoken = spoken_english_post_process(response)
    print("\nSpoken English version:\n", spoken)
