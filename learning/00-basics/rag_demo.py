import requests
import math

EMBED_URL = "http://localhost:11434/api/embeddings"
CHAT_URL = "http://localhost:11434/api/chat"
EMBED_MODEL = "nomic-embed-text"
CHAT_MODEL = "llama3.1:8b"

def get_embedding(text):
    """
    Sends ONE piece of text to Ollama's embeddings endpoint.
    Unlike /api/chat (which takes a 'messages' list), /api/embeddings
    takes a single 'prompt' string and returns a vector — a list of
    a few hundred numbers representing that text's meaning.
    """
    payload = {
        "model": EMBED_MODEL,
        "prompt": text
    }
    response = requests.post(EMBED_URL, json=payload)
    data = response.json()
    print("RAW RESPONSE:", data)
    return data['embedding']

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


# --- Step 1: our tiny "knowledge base" (pretend these are chunks from a real project) ---
knowledge_base = [
    "void saveUserSettings(String key, String value) {\n  final prefs = SharedPreferences.getInstance();\n  prefs.setString(key, value);\n}",
    "Future<User> fetchUserProfile(String userId) async {\n  final response = await http.get(Uri.parse('/api/users/$userId'));\n  return User.fromJson(jsonDecode(response.body));\n}",
    "class AppColors {\n  static const primary = Color(0xFF2563EB);\n  static const secondary = Color(0xFF64748B);\n}",
]

print("Step 1: embedding the knowledge base...")
kb_embeddings = [get_embedding(chunk) for chunk in knowledge_base]
print(f"   embedded {len(kb_embeddings)} chunks.\n")

# --- Step 2: the user's question ---
question = "how do I save a setting locally?"
print(f"Step 2: question -> {question!r}")
question_embedding = get_embedding(question)

# --- Step 3: retrieval — find the most similar chunk ---
scores = [cosine_similarity(question_embedding, kb_emb) for kb_emb in kb_embeddings]
best_index = scores.index(max(scores))

print("\nStep 3: similarity scores against each chunk:")
for i, score in enumerate(scores):
    marker = " <-- best match" if i == best_index else ""
    print(f"  chunk {i}: {score:.4f}{marker}")

best_chunk = knowledge_base[best_index]

# --- Step 4: augmented generation — ask the LLM using the retrieved chunk as context ---
prompt = f"""Here is a relevant code snippet from the project:

{best_chunk}

Question: {question}

Answer using the style/pattern shown in the snippet above."""

print("\nStep 4: asking the local model, grounded in the retrieved chunk...\n")
chat_payload = {
    "model": CHAT_MODEL,
    "messages": [{"role": "user", "content": prompt}],
    "stream": False,
}
response = requests.post(CHAT_URL, json=chat_payload)
answer = response.json()["message"]["content"]

print("=== ANSWER ===")
print(answer)