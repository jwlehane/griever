import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

from app.core import TaxGrieveCore

core = TaxGrieveCore()

print("Testing get_subject_profile...")
subject = core.get_subject_profile("33 Cedar Heights, Rhinebeck")
if subject:
    print(f"Subject found: {subject['address']} - {subject.get('sqft')} sqft")
    
    # ensure it's in DB
    subject_id = core.ensure_property(subject)
    print(f"Subject ID in DB: {subject_id}")
    
    print("Testing discover_comps_live...")
    generator = core.discover_comps_live(subject, subject_id, force_verify=False)
    
    for update in generator:
        print(f"Update: {update['status']} - {update.get('message', '')} {update.get('comp', {}).get('address', '')}")
        if update['status'] == 'complete':
            print(f"Discovered {len(update['comps'])} comps")
            break
else:
    print("Subject not found.")
