"""
llm.py — the ONLY file that talks to Ollama.

Keeping all model calls here means the rest of the agent does not care
which model or server we use. To swap Ollama for something else later,
you only change this file.
"""

import json
import requests

from agent import config


def embed(text, kind="document"):
    """Turn text into a vector (list of floats).

    nomic-embed-text was trained with a prefix telling it what the text is:
      - "search_document: " for things we store in the index
      - "search_query: "    for the user's question
    Using the right prefix noticeably improves search quality.
    """
    prefix = "search_query: " if kind == "query" else "search_document: "
    response = requests.post(
        f"{config.OLLAMA_URL}/api/embeddings",
        json={"model": config.EMBED_MODEL, "prompt": prefix + text},
        timeout=120,
    )
    data = response.json()
    if "embedding" not in data:
        raise ValueError(f"Embedding failed: {data}")
    return data["embedding"]


def chat(messages, json_mode=False, temperature=None):
    """Send a conversation to the chat model and return its reply text.

    messages: list like [{"role": "system", "content": "..."},
                         {"role": "user",   "content": "..."}]
    json_mode: if True, Ollama forces the model to reply with valid JSON.
               We use this whenever code (not a human) reads the answer.
    """
    payload = {
        "model": config.CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": config.NUM_CTX,
            "num_predict": config.MAX_OUTPUT_TOKENS,
            "temperature": config.TEMPERATURE if temperature is None else temperature,
        },
    }
    if json_mode:
        payload["format"] = "json"
    response = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=600)
    return response.json()["message"]["content"]


def chat_json(messages):
    """Like chat(), but parses the reply into a Python dict.
    Returns {} if the model produced something unparseable."""
    try:
        return json.loads(chat(messages, json_mode=True))
    except json.JSONDecodeError:
        return {}
