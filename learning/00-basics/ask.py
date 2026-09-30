import requests

url = "http://localhost:11434/api/chat"

payload = {
    "model":"llama3.1:8b",
    "messages": [
        {
            "role": "user",
            "content": "Hello, how are you?"
        }
    ],
    "stream" : False,
}

response = requests.post(url, json=payload)

data = response.json()

print(data['message']['content'])