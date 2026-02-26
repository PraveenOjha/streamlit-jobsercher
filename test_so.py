import requests

url = "https://api.stackexchange.com/2.3/questions"
params = {
    "order": "desc",
    "sort": "creation",
    "tagged": "react-native",
    "site": "stackoverflow",
    "filter": "withbody"
}

resp = requests.get(url, params=params)
print(resp.status_code)
if resp.status_code == 200:
    items = resp.json().get("items", [])
    if items:
        print(items[0].keys())
        print(items[0].get("title"))
