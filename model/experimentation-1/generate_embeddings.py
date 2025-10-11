from chromadb import PersistentClient
import os, re
from ollama import embeddings

client = PersistentClient(path="./eunomia_db")
collection = client.get_or_create_collection("data_and_QAs")

# Use Ollama to generate embeddings
def get_embedding(text): 
    response = embeddings(
        model='nomic-embed-text',
        prompt=text
    )
    r = response['embedding']
    # print(r)
    return r

for filename in os.listdir('./QApairs_dataset'):
    with open(os.path.join('./QApairs_dataset', filename)) as f:
        content = f.read()
        title = re.search(r"<caseName>(.*?)</caseName>", content, re.S).group(1).strip()
         
    chunks = [content[i:i+1000] for i in range(0, len(content), 1000)]
    e = []
    for c in chunks:
        r = embeddings(model="nomic-embed-text", prompt=c)
        if r is None or not r:
            print(f"Failed to get embeddings for URL: {filename}")
            continue  # Skip this iteration if embedding is invalid
        e.extend(r)

    collection.add(
        documents=[content],
        ids=[title],
        embeddings=[e]
    )
    print("added embeddings for: ", filename)
    
    
