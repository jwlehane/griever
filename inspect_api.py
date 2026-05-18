import requests
import json
session = requests.Session()
session.get("https://gis.dutchessny.gov/parcelaccess/")
headers = {"Referer": "https://gis.dutchessny.gov/parcelaccess/", "User-Agent": "Mozilla/5.0"}

# Get parcelgrid for 33 Cedar Heights, swis 135089
params = {'number': '33', 'street': 'CEDAR HEIGHTS', 'swis': '135089'}
resp = session.get("https://gis.dutchessny.gov/parcelaccess/asp/search_extract_addresses.asp", params=params, headers=headers)
data = resp.json()
if data.get('success') and data.get('data'):
    grid = data['data'][0].get('parcelgrid') or data['data'][0].get('id')
    print("Grid:", grid)
    
    # Get details
    resp2 = session.post("https://gis.dutchessny.gov/parcelaccess/asp/search_extract_parcelgrids.asp", data={'parcelgrid': grid}, headers=headers)
    print("Primary keys:", resp2.json().get('data', [{}])[0].keys())
    
    primary = resp2.json().get('data', [{}])[0]
    
    params3 = {
        'parcelid': primary.get('parcel_id'),
        'county': primary.get('swis', '')[:2],
        'town': primary.get('swis', '')[2:4],
        'village': primary.get('swis', '')[4:6]
    }
    resp3 = session.get("https://gis.dutchessny.gov/parcelaccess/asp/get_property_details.asp", params=params3, headers=headers)
    details = resp3.json().get('data', {})
    resbldg = details.get('resbldg', [{}])[0] if details.get('resbldg') else {}
    print("Resbldg keys:", resbldg.keys())
    print("Condition:", resbldg.get('overall_cond_desc'), "Grade:", resbldg.get('bldg_grade_desc'))
