from semantic_search import FAISSSemanticSearch

def test_semantic_search():
    ss = FAISSSemanticSearch()
    results = ss.search("supreme court", n=2)
    # assert "<results>" in results
    # assert results.count("<result>") <= 2
    print(results)
    
if __name__ == "__main__":  
    test_semantic_search()