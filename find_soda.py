import requests

url = "https://data.ny.gov/api/views.json"
resp = requests.get(url)
for view in resp.json():
    name = view.get('name', '')
    if 'Property Assessment Data' in name or 'Local Assessment Rolls' in name:
        print(f"Name: {name}")
        print(f"ID: {view.get('id')}")
