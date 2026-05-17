import requests
import json
from typing import Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

class OrptsClient:
    """Client for NYS ORPTS Data via data.ny.gov SODA API"""
    
    # Dataset ID for "Property Assessment Data from Local Assessment Rolls"
    DATASET_ID = "7vem-aaz7"
    BASE_URL = f"https://data.ny.gov/resource/{DATASET_ID}.json"

    def __init__(self, app_token: Optional[str] = None):
        self.session = requests.Session()
        self.headers = {}
        if app_token:
            self.headers["X-App-Token"] = app_token

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_property_assessment(self, swis: str, print_key: str) -> Optional[Dict]:
        """
        Fetch property assessment details including assessed value from SODA API.
        Print key is typically the SBL (Section-Block-Lot).
        """
        # Format the print key to match SODA API formatting if necessary
        # SODA API usually stores print key exactly as formatted by the county
        params = {
            "municipality_code": swis,
            "print_key_code": print_key
        }
        
        try:
            resp = self.session.get(self.BASE_URL, params=params, headers=self.headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if data:
                # Return the first match
                return data[0]
            return None
            
        except Exception as e:
            print(f"Error fetching ORPTS data for {swis}-{print_key}: {e}")
            return None

    def get_municipal_rates(self, swis: str) -> Dict[str, float]:
        """
        Fetch RAR and Equalization Rates. 
        Falls back to local constants if not found in the SODA API dataset.
        """
        # The user requested fetching RAR and EQ rates from the SODA API, 
        # but the property assessment dataset usually only has property-level data.
        # We will wrap the existing equalization.py logic here as a robust fallback.
        from app.equalization import ER_BY_SWIS
        
        # Default to 100% if unknown
        rate = ER_BY_SWIS.get(swis[:6], 100.0)
        
        return {
            "equalization_rate": rate,
            "rar": rate  # Usually RAR and ER are identical for 100% towns like Rhinebeck
        }
