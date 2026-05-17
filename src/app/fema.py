import requests
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

class FemaClient:
    """Client for FEMA National Flood Hazard Layer (NFHL) ArcGIS REST API"""

    BASE_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHLWMS/MapServer/identify"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def is_in_flood_zone(self, lat: float, lon: float) -> bool:
        """
        Query FEMA MapServer to determine if coordinates intersect a Special Flood Hazard Area.
        Returns True if the point is in a high-risk flood zone (e.g. Zone A, AE, VE).
        """
        if not lat or not lon:
            return False

        # Identify parameters for ArcGIS REST API
        # We need to construct a small bounding box (mapExtent) around the point to satisfy the API
        buffer = 0.001
        extent = f"{lon - buffer},{lat - buffer},{lon + buffer},{lat + buffer}"

        params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "sr": "4326",
            "layers": "all",
            "tolerance": "2",  # Pixel tolerance
            "mapExtent": extent,
            "imageDisplay": "800,600,96",
            "returnGeometry": "false",
            "f": "json"
        }

        try:
            resp = self.session.get(self.BASE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            for res in results:
                # Check attributes for flood zone designation
                attrs = res.get("attributes", {})
                zone = attrs.get("FLD_ZONE", "").upper()
                
                # Special Flood Hazard Areas start with A or V
                if zone and (zone.startswith("A") or zone.startswith("V")):
                    return True

            return False

        except Exception as e:
            print(f"Error querying FEMA API for {lat},{lon}: {e}")
            # Fail closed: assume not in flood zone if API fails
            return False
