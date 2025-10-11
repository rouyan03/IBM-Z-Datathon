from chromadb import PersistentClient
from ollama import embeddings
import xml.etree.ElementTree as ET

# --- Initialize Chroma persistent client ---
client = PersistentClient(path="./eunomia_db")
collection = client.get_or_create_collection("all_XML")



# --- Path to your giant XML file ---
xml_file = "./normalized_enhanced.xml"

# --- Parse the XML ---
tree = ET.parse(xml_file)
root = tree.getroot()

# Ensure we’re in <Cases> ... <Case> structure
if root.tag.lower() != "cases":
    raise ValueError("Expected root element <Cases>")

# --- Iterate over each <Case> element ---
for case in root.findall("Case"):
    name = case.get("name")
    slug = case.get("slug")

    # Combine all text inside this <Case> element
    content = ET.tostring(case, encoding="unicode", method="xml")

    # Optionally chunk large cases (for models with token limits)
    chunks = [content[i:i + 1000] for i in range(0, len(content), 1000)]
    
    # Collect embeddings for each chunk
    embeddings_list = []
    for chunk in chunks:
        emb = embeddings(model="nomic-embed-text", prompt=chunk)
        if not emb:
            print(f"⚠️ Skipping failed chunk in case: {name}")
            continue
        embeddings_list.extend(emb)
    
    # --- Save to Chroma ---
    collection.add(
        documents=[content],
        ids=[slug],
        embeddings=[embeddings_list]
    )

    print(f"✅ Added embeddings for case: {name}")

print("🎉 All cases processed and embeddings stored.")

    