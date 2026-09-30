import requests
import math

url = "http://localhost:11434/api/embeddings"
model = "nomic-embed-text"

def get_embedding(text):
    """
    Sends ONE piece of text to Ollama's embeddings endpoint.
    Unlike /api/chat (which takes a 'messages' list), /api/embeddings
    takes a single 'prompt' string and returns a vector — a list of
    a few hundred numbers representing that text's meaning.
    """
    payload = {
        "model": model,
        "prompt": text
    }
    response = requests.post(url, json=payload)
    data = response.json()
    print("RAW RESPONSE:", data)
    return data['embedding']

# Calculate cosine similarity
def cosine_similarity(vec1, vec2):
    """
    Measures how similar two vectors are, from -1 (opposite meaning)
    to 1 (identical meaning). Formula: (A . B) / (|A| * |B|)
    - A . B  = dot product (multiply matching positions, sum them up)
    - |A|    = magnitude/length of vector A (Pythagoras: sqrt of sum of squares)
    """
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.hypot(*vec1)
    magnitude2 = math.hypot(*vec2)
    return dot_product / (magnitude1 * magnitude2) if magnitude1 * magnitude2 != 0 else 0


# --- Test it ---
sentence_1 = "I love programming"
sentence_2 = "I enjoy coding"
sentence_3 = "The weather is nice today"

embedding_1 = get_embedding(sentence_1)
embedding_2 = get_embedding(sentence_2)
embedding_3 = get_embedding(sentence_3)

print(f"Vector length: {len(embedding_1)} numbers")  # just to see the size

score_related = cosine_similarity(embedding_1, embedding_2)
score_unrelated = cosine_similarity(embedding_1, embedding_3)

print(f"\n'{sentence_1}' vs '{sentence_2}' -> similarity: {score_related:.4f}")
print(f"'{sentence_1}' vs '{sentence_3}' -> similarity: {score_unrelated:.4f}")
