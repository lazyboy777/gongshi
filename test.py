import requests
  
url = "https://api.edgefn.net/v1/chat/completions"
headers = {
    "Authorization": "Bearer sk-bM5PkoitY4HmZ77F8312EbBe01B040208cF3152fEc5029E0", 
    "Content-Type": "application/json"
}
data = {
    "model": "Qwen3-32B-FP8",
    "messages": [{"role": "user", "content": "Hello, how are you?"}]
}

response = requests.post(url, headers=headers, json=data)
print(response.json())