#!/usr/bin/env python3
"""
Convert DealSauce CSV exports to REIflow JSON format and merge into reiflow_sellers.json
Usage: python3 dealsauce_to_reiflow.py
"""

import json, csv, os, re
from datetime import date

REIFLOW_DIR = '/Users/carlossandoval/reiflow-app'
SELLERS_JSON = f'{REIFLOW_DIR}/reiflow_sellers.json'
IMPORT_DATE = str(date.today())

CSV_FILES = [
    '/tmp/claude/dealsauce-all/lpp-export-78f442e8-c3b9-4981-a818-e6c4606c7610.csv',
    '/tmp/claude/dealsauce-all/lpp-export-9a911d23-70ec-4a2d-9e85-8fe818a193f0.csv',
    '/tmp/claude/dealsauce-all/lpp-export-b00dcfe1-672a-4254-9868-0b78c0acf685.csv',
]

def clean_phone(phone):
    """Strip to digits only, return empty string if not 10 digits."""
    if not phone:
        return ''
    digits = re.sub(r'\D', '', str(phone))
    return digits if len(digits) == 10 else ''

def clean_price(val):
    """Convert '$1,234,567' or '1234567' to float."""
    if not val:
        return 0.0
    cleaned = re.sub(r'[\$,]', '', str(val)).strip()
    try:
        return float(cleaned)
    except:
        return 0.0

def get_best_phones(row):
    """Pull up to 3 non-DNC, non-litigator phone numbers from up to 3 contacts."""
    phones = []
    emails = []

    contact_groups = [
        ('Contact1Phone_1', 'Contact1Phone_1_DNC', 'Contact1Phone_1_Litigator', 'Contact1Email_1',
         'Contact1Phone_2', 'Contact1Phone_2_DNC', 'Contact1Phone_2_Litigator', 'Contact1Email_2',
         'Contact1Phone_3', 'Contact1Phone_3_DNC', 'Contact1Phone_3_Litigator', 'Contact1Email_3'),
        ('Contact2Phone_1', 'Contact2Phone_1_DNC', 'Contact2Phone_1_Litigator', 'Contact2Email_1',
         'Contact2Phone_2', 'Contact2Phone_2_DNC', 'Contact2Phone_2_Litigator', 'Contact2Email_2',
         'Contact2Phone_3', 'Contact2Phone_3_DNC', 'Contact2Phone_3_Litigator', 'Contact2Email_3'),
        ('Contact3Phone_1', 'Contact3Phone_1_DNC', 'Contact3Phone_1_Litigator', 'Contact3Email_1',
         'Contact3Phone_2', 'Contact3Phone_2_DNC', 'Contact3Phone_2_Litigator', 'Contact3Email_2',
         'Contact3Phone_3', 'Contact3Phone_3_DNC', 'Contact3Phone_3_Litigator', 'Contact3Email_3'),
    ]

    for group in contact_groups:
        for i in range(0, len(group), 4):
            ph_col, dnc_col, lit_col, em_col = group[i], group[i+1], group[i+2], group[i+3]
            phone = clean_phone(row.get(ph_col, ''))
            dnc = str(row.get(dnc_col, 'False')).strip().lower() == 'true'
            litigator = str(row.get(lit_col, 'False')).strip().lower() == 'true'
            email = str(row.get(em_col, '')).strip()

            if phone and not dnc and not litigator and phone not in phones:
                phones.append(phone)
            if email and email not in emails:
                emails.append(email)

            if len(phones) >= 3:
                break
        if len(phones) >= 3:
            break

    while len(phones) < 3:
        phones.append('')

    return phones[0], phones[1], phones[2], emails[0] if emails else ''

def row_to_lead(row, lead_id):
    first = str(row.get('FirstName', '') or '').strip()
    last = str(row.get('LastName', '') or '').strip()
    owner = f"{first} {last}".strip() or str(row.get('Contact1Name', '') or '').strip()

    prop_addr = str(row.get('PropertyAddress', '') or '').strip()
    prop_city = str(row.get('PropertyCity', '') or '').strip()
    prop_state = str(row.get('PropertyState', '') or '').strip()
    prop_zip = str(row.get('PropertyPostalCode', '') or '').strip()
    county = str(row.get('County', '') or '').strip()
    full_addr = f"{prop_addr}, {prop_city}, {prop_state}, {prop_zip}".strip(', ')

    prop_type = str(row.get('PropertyType', 'Single Family') or 'Single Family').strip()
    sqft = int(clean_price(row.get('SquareFootage', 0)))
    beds = str(row.get('Beds', '') or '').strip()
    baths = str(row.get('Baths', '') or '').strip()

    ph1, ph2, ph3, email = get_best_phones(row)

    # Valuation fields (only in some exports)
    est_value = clean_price(row.get('AVM', 0) or row.get('MarketValue', 0))
    loan_bal = clean_price(row.get('LoanAmount', 0) or row.get('EstimatedMortgageBalance', 0))
    equity = max(0, est_value - loan_bal) if est_value > 0 else 0

    status = 'Not Contacted' if ph1 else 'Need Skip Trace'

    notes_parts = []
    if sqft:
        notes_parts.append(f"{sqft} sqft")
    if beds:
        notes_parts.append(f"{beds}bd/{baths}ba")
    last_sale = str(row.get('LastSalesDate', '') or '').strip()
    last_price = clean_price(row.get('LastSalesPrice', 0))
    if last_sale and last_price:
        notes_parts.append(f"Last sold {last_sale} @ ${last_price:,.0f}")
    notes = ' | '.join(notes_parts)

    return {
        'id': lead_id,
        'type': 'seller',
        'propType': prop_type,
        'owner': owner,
        'phone': ph1,
        'phone2': ph2,
        'phone3': ph3,
        'email': email,
        'address': prop_addr,
        'fullAddress': full_addr,
        'source': f'DealSauce ({prop_state})',
        'listPrice': 0,
        'askingPrice': 0,
        'notes': notes,
        'status': status,
        'importedAt': IMPORT_DATE,
        'excess': 0,
        'cut': 0,
        'county': f'{county}, {prop_state}' if county else prop_state,
        'loanBal': loan_bal,
        'estValue': est_value,
        'equity': equity,
    }

# Load existing sellers
with open(SELLERS_JSON) as f:
    sellers = json.load(f)

existing_ids = {s['id'] for s in sellers}
existing_addresses = {s.get('fullAddress', '').lower().strip() for s in sellers}

print(f"Existing sellers in app: {len(sellers)}")

new_leads = []
skipped_dupes = 0
skipped_no_data = 0
counter = 0

for csv_path in CSV_FILES:
    if not os.path.exists(csv_path):
        print(f"  MISSING: {csv_path}")
        continue

    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"\nProcessing {os.path.basename(csv_path)}: {len(rows)} rows")

    file_added = 0
    for row in rows:
        prop_addr = str(row.get('PropertyAddress', '') or '').strip()
        prop_city = str(row.get('PropertyCity', '') or '').strip()
        prop_state = str(row.get('PropertyState', '') or '').strip()
        prop_zip = str(row.get('PropertyPostalCode', '') or '').strip()
        full_addr = f"{prop_addr}, {prop_city}, {prop_state}, {prop_zip}".strip(', ').lower()

        if not prop_addr:
            skipped_no_data += 1
            continue

        if full_addr in existing_addresses:
            skipped_dupes += 1
            continue

        lead_id = f'DS-{prop_state}-{counter:04d}'
        lead = row_to_lead(row, lead_id)
        new_leads.append(lead)
        existing_addresses.add(full_addr)
        counter += 1
        file_added += 1

    print(f"  Added: {file_added} leads")

print(f"\nSkipped duplicates: {skipped_dupes}")
print(f"Skipped (no address): {skipped_no_data}")
print(f"New leads to add: {len(new_leads)}")

if not new_leads:
    print("Nothing to add. Exiting.")
    exit()

# Stats
with_phone = sum(1 for l in new_leads if l['phone'])
need_skip = sum(1 for l in new_leads if not l['phone'])
print(f"  With phone: {with_phone} | Need skip trace: {need_skip}")

# Merge — new leads go to front so they appear first in the dialer
merged = new_leads + sellers

with open(SELLERS_JSON, 'w') as f:
    json.dump(merged, f, indent=2)

print(f"\nSaved. Total sellers now: {len(merged)}")
print("Run inject_leads.py next to bake into index.html")
