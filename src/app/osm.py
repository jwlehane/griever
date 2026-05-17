import requests
from typing import Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

class OsmClient:
    """Client for OpenStreetMap Overpass API"""

    OVERPASS_URL = "https://overpass-api.de/api/interpreter"

    def __init__(self):
        self.session = requests.Session()
        # Overpass requires a descriptive User-Agent
        self.session.headers.update({
            "User-Agent": "TaxGrieveNY/1.0 (RealEstate Valuation Engine)"
        })

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def check_proximities(self, lat: float, lon: float, radius_meters: int = 500) -> Dict[str, bool]:
        """
        Check if the property is within a certain radius of specific features.
        Returns a dict of boolean flags for each category.
        """
        if not lat or not lon:
            return {"nuisance_rail": False, "nuisance_highway": False, "amenity_park": False}

        # Build an Overpass QL query
        # We look for:
        # 1. Railway (Amtrak/freight)
        # 2. Highway (Route 9 / primary)
        # 3. Leisure (Park)
        
        query = f"""
        [out:json][timeout:10];
        (
          way["railway"="rail"](around:{radius_meters},{lat},{lon});
          way["highway"~"primary|trunk"](around:{radius_meters},{lat},{lon});
          way["leisure"="park"](around:{radius_meters},{lat},{lon});
        );
        out body;
        """

        results = {
            "nuisance_rail": False,
            "nuisance_highway": False,
            "amenity_park": False
        }

        try:
            resp = self.session.post(self.OVERPASS_URL, data={"data": query}, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            elements = data.get("elements", [])
            for el in elements:
                tags = el.get("tags", {})
                
                if "railway" in tags and tags["railway"] == "rail":
                    results["nuisance_rail"] = True
                
                if "highway" in tags and tags["highway"] in ["primary", "trunk"]:
                    results["nuisance_highway"] = True
                    
                if "leisure" in tags and tags["leisure"] == "park":
                    results["amenity_park"] = True

            return results

        except Exception as e:
            print(f"Error querying Overpass API for {lat},{lon}: {e}")
            return results
