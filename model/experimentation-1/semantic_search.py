
def semantic_search(question="", n=3):
    from ollama import embeddings
    import subprocess
    from chromadb import PersistentClient

    # Create a persistent Chroma client
    client = PersistentClient(path="./eunomia_db")
    # Get or create the collection
    collection = client.get_or_create_collection("all_XML")

    
    q_embedding = embeddings(model="nomic-embed-text", prompt=question) 
    results = collection.query(
        query_embeddings=[q_embedding],
        n_results=n
    )
    
    
semantic_search("I am having a divorce with my husband because he cheated on me. What legal precedemt is there to such a case and what can I do about the following proceedings?", 5)