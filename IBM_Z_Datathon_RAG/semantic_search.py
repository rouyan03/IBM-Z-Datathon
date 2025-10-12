# in Colab, run these first. Uncomment if needed.
# !curl https://ollama.ai/install.sh | sh
# !ollama serve &  # runs in background

import numpy as np
import faiss
import requests
import xml.etree.ElementTree as ET
import sqlite3
import struct
from chromadb import PersistentClient
from typing import List, Tuple

class FAISSSemanticSearch:
    def __init__(self, chroma_path: str = "./eunomia_db", collection_name: str = "all_XML", 
                 ollama_url: str = None):
        """
        Initialize FAISS search with ChromaDB data.
        
        Args:
            chroma_path: Path to ChromaDB
            collection_name: ChromaDB collection name
            ollama_url: Ollama endpoint (default: http://localhost:11434)
                       For Colab, use ngrok tunnel or remote server URL
        """
        self.chroma_path = chroma_path
        self.client = PersistentClient(path=chroma_path)
        self.collection = self.client.get_or_create_collection(collection_name)
        self.ollama_url = ollama_url or "http://localhost:11434"
        self.index = None
        self.metadata = None
        self.embeddings = None
        self._build_index()
    
    def _embed_text(self, text: str) -> List[float]:
        """Embed text using Ollama's nomic-embed-text."""
        response = requests.post(
            f"{self.ollama_url}/api/embed",
            json={"model": "nomic-embed-text", "input": text}
        )
        return response.json()["embeddings"][0]
    
    def _build_index(self):
        """Build FAISS index from ChromaDB SQLite database."""
        # Connect to SQLite
        db_path = f"{self.chroma_path}/chroma.sqlite3"
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
        
        # Decode BLOB vectors
        embeddings = []
        ids_map = {}
        
        for seq_id, vector_blob, encoding in rows:
            if encoding == "FLOAT32":
                # Decode FLOAT32 BLOB
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
        
        # Store metadata for retrieval (match with embeddings)
        self.metadata = [
            {
                "id": id_,
                "document": doc,
                "meta": meta
            }
            for id_, doc, meta in zip(ids, documents, metadatas)
        ]
        
        # Trim embeddings and metadata to match (in case counts differ)
        min_len = min(len(embeddings), len(self.metadata))
        embeddings = embeddings[:min_len]
        self.metadata = self.metadata[:min_len]
        
        self.embeddings = embeddings
        
        # Create FAISS index (L2 distance)
        dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(embeddings)
        
        conn.close()
        print(f"✓ FAISS index built with {len(self.metadata)} documents from SQLite")
    
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
        
        # Embed query
        query_embedding = np.array([self._embed_text(query)], dtype=np.float32)
        
        # Search FAISS
        distances, indices = self.index.search(query_embedding, min(n, len(self.metadata)))
        
        # Convert L2 distances to similarity scores (0-1 range)
        # Using: similarity = 1 / (1 + distance)
        scores = 1 / (1 + distances[0])
        
        # Build XML results
        results_elem = ET.Element("results", num=str(n))
        
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
        return xml_string


# Example usage
if __name__ == "__main__":
    # Local usage (Ollama running on localhost)
    search = FAISSSemanticSearch()
    
    # For Colab with remote Ollama, use:
    # search = FAISSSemanticSearch(ollama_url="https://your-ngrok-url.ngrok.io")
    # OR setup Ollama in Colab first with: !curl https://ollama.ai/install.sh | sh
    
    query = "motions to adjourn without notice"
    results_xml = search.search(query, n=3)
    print(results_xml)