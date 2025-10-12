"""
semantic_search.py - FAISS semantic search WITHOUT Ollama

Uses sentence-transformers (all-MiniLM-L6-v2) for local embeddings.
Much faster and simpler than Ollama - no external service needed!

Installation:
  pip install sentence-transformers faiss-cpu chromadb
  
For GPU support, use faiss-gpu instead of faiss-cpu
"""

import numpy as np
import faiss
import xml.etree.ElementTree as ET
import sqlite3
import struct
from chromadb import PersistentClient
from typing import List, Tuple
from sentence_transformers import SentenceTransformer


class FAISSSemanticSearch:
    def __init__(self, chroma_path: str = "./eunomia_db", 
                 collection_name: str = "all_XML",
                 model_name: str = None):
        """
        Initialize FAISS search with ChromaDB data and local embeddings.
        
        Args:
            chroma_path: Path to ChromaDB persistent storage
            collection_name: ChromaDB collection name
            model_name: Sentence-Transformers model name (auto-detected if None)
                       Options:
                       - "all-MiniLM-L6-v2" (384 dims, very fast)
                       - "all-mpnet-base-v2" (768 dims, higher quality)
                       - "paraphrase-MiniLM-L6-v2" (384 dims, good balance)
        """
        self.chroma_path = chroma_path
        self.collection_name = collection_name
        
        # Initialize ChromaDB first to detect dimension
        print(f"[INIT] Connecting to ChromaDB at {chroma_path}")
        self.client = PersistentClient(path=chroma_path)
        self.collection = self.client.get_or_create_collection(collection_name)
        
        self.index = None
        self.metadata = None
        self.embeddings = None
        
        # Detect embedding dimension from stored embeddings
        detected_dim = self._detect_embedding_dimension()
        print(f"[INIT] Detected embedding dimension from ChromaDB: {detected_dim}")
        
        # Auto-select model based on dimension if not specified
        if model_name is None:
            if detected_dim == 384:
                model_name = "all-MiniLM-L6-v2"
            elif detected_dim == 768:
                model_name = "all-mpnet-base-v2"
            else:
                print(f"[WARNING] Unknown dimension {detected_dim}, defaulting to all-MiniLM-L6-v2")
                model_name = "all-MiniLM-L6-v2"
        
        self.model_name = model_name
        
        # Initialize embedding model
        print(f"[INIT] Loading SentenceTransformer model: {model_name}")
        self.model = SentenceTransformer(model_name)
        model_dim = self.model.get_sentence_embedding_dimension()
        print(f"✓ Model loaded. Embedding dimension: {model_dim}")
        
        if model_dim != detected_dim:
            print(f"[WARNING] Model dimension {model_dim} != stored dimension {detected_dim}")
            print(f"[WARNING] This may cause dimension mismatch errors")
        
        self._build_index()
    
    def _detect_embedding_dimension(self) -> int:
        """Detect the embedding dimension from stored vectors in ChromaDB."""
        try:
            db_path = f"{self.chroma_path}/chroma.sqlite3"
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get first embedding to detect dimension
            cursor.execute("""
                SELECT vector, encoding FROM embeddings_queue 
                WHERE vector IS NOT NULL
                LIMIT 1
            """)
            row = cursor.fetchone()
            conn.close()
            
            if row:
                vector_blob, encoding = row
                if encoding == "FLOAT32":
                    num_floats = len(vector_blob) // 4
                    return num_floats
            
            return 384  # default fallback
        except Exception as e:
            print(f"[WARNING] Could not detect dimension: {e}")
            return 384
    
    def _embed_text(self, text: str) -> np.ndarray:
        """
        Embed text using SentenceTransformer (local, no external service needed).
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding as numpy array
        """
        # SentenceTransformer returns (1, embedding_dim) for single strings
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)
    
    def _build_index(self):
        """Build FAISS index from ChromaDB SQLite database."""
        db_path = f"{self.chroma_path}/chroma.sqlite3"
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get all embeddings from embeddings_queue
            cursor.execute("""
                SELECT id, vector, encoding FROM embeddings_queue 
                WHERE vector IS NOT NULL
            """)
            rows = cursor.fetchall()
            
            if not rows:
                raise ValueError("No embeddings found in SQLite database!")
            
            print(f"[INDEX] Found {len(rows)} pre-computed embeddings in SQLite")
            
            # Decode BLOB vectors
            embeddings = []
            ids_map = {}
            
            for seq_id, vector_blob, encoding in rows:
                if encoding == "FLOAT32":
                    num_floats = len(vector_blob) // 4
                    vector = struct.unpack(f"{num_floats}f", vector_blob)
                    embeddings.append(list(vector))
                    ids_map[seq_id] = seq_id
            
            embeddings = np.array(embeddings, dtype=np.float32)
            
            # Get document info from ChromaDB
            all_data = self.collection.get()
            
            if not all_data or not all_data["ids"]:
                raise ValueError("ChromaDB collection is empty!")
            
            ids = all_data["ids"]
            documents = all_data["documents"]
            metadatas = all_data["metadatas"] if all_data["metadatas"] else [{}] * len(ids)
            
            # Store metadata for retrieval
            self.metadata = [
                {
                    "id": id_,
                    "document": doc,
                    "meta": meta
                }
                for id_, doc, meta in zip(ids, documents, metadatas)
            ]
            
            # Trim embeddings and metadata to match
            min_len = min(len(embeddings), len(self.metadata))
            embeddings = embeddings[:min_len]
            self.metadata = self.metadata[:min_len]
            
            self.embeddings = embeddings
            
            # Create FAISS index (L2 distance)
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatL2(dimension)
            self.index.add(embeddings)
            
            conn.close()
            print(f"✓ FAISS index built with {len(self.metadata)} documents")
            
        except Exception as e:
            print(f"[ERROR] Failed to build index: {e}")
            raise
    
    def search(self, query: str, n: int = 3) -> str:
        """
        Semantic search and return results as XML.
        
        Args:
            query: Search query string
            n: Number of results to return
        
        Returns:
            XML string with results
        """
        if self.index is None:
            raise RuntimeError("FAISS index not initialized!")
        
        try:
            # Embed query locally
            print(f"[SEARCH] Embedding query: {query[:50]}...")
            query_embedding = self._embed_text(query)
            
            # Reshape for FAISS (needs 2D array)
            query_embedding = query_embedding.reshape(1, -1)
            
            # Search FAISS
            distances, indices = self.index.search(query_embedding, min(n, len(self.metadata)))
            
            # Convert L2 distances to similarity scores (0-1 range)
            # Using: similarity = 1 / (1 + distance)
            scores = 1 / (1 + distances[0])
            
            # Build XML results
            results_elem = ET.Element("results", num=str(len(indices[0])))
            
            for idx, score in zip(indices[0], scores):
                result_elem = ET.SubElement(results_elem, "result")
                result_elem.set("id", self.metadata[idx]["id"])
                result_elem.set("score", f"{score:.3f}")
                
                # Parse and preserve original XML tags
                doc = self.metadata[idx]["document"]
                try:
                    # Try to parse as XML and append child elements
                    doc_elem = ET.fromstring(f"<root>{doc}</root>")
                    for child in doc_elem:
                        result_elem.append(child)
                except ET.ParseError:
                    # If not valid XML, just set as text
                    result_elem.text = doc
            
            # Convert to string with proper formatting
            xml_string = ET.tostring(results_elem, encoding="unicode")
            print(f"[SEARCH] Returned {len(indices[0])} results")
            return xml_string
        
        except Exception as e:
            print(f"[ERROR] Search failed: {e}")
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"Semantic search failed: {str(e)}")


# Example usage
if __name__ == "__main__":
    try:
        print("[STARTUP] Initializing semantic search (no Ollama needed!)")
        search = FAISSSemanticSearch()
        
        query = "motions to adjourn without notice"
        print(f"\n[TEST] Searching for: {query}")
        results_xml = search.search(query, n=3)
        print("\nResults:")
        print(results_xml)
    
    except Exception as e:
        print(f"[ERROR] {e}")
        print("\nTroubleshooting:")
        print("1. Install dependencies: pip install sentence-transformers faiss-cpu chromadb")
        print("2. Ensure ChromaDB database exists at ./eunomia_db/")
        print("3. Check that ChromaDB has indexed your documents")