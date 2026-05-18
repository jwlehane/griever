import requests
import json
resp = requests.get("https://data.ny.gov/resource/7vem-aaz7.json?$limit=1")
if resp.status_code == 200:
    print(list(resp.json()[0].keys()))
else:
    print("Error:", resp.status_code, resp.text)
