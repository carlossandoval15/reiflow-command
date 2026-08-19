#!/usr/bin/env python3
"""
Parse every DealSauce CSV export sitting in incoming/, convert to ReiFlow lead
records (same schema as dealsauce_to_reiflow.py / parse_leads.py), dedupe
against what's already in reiflow_foreclosures.json (by lowercased full
address), and write the merged result back. Processed CSVs get moved to
incoming/processed/ so a re-run never double-counts them.

Prints a single JSON summary line to stdout: SUMMARY_JSON:{...}
"""
import csv
import json
import os
import re
import sys
import shutil
from datetime import date, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
REIFLOW_DIR = os.path.dirname(BASE)  # ~/reiflow-command
INCOMING_DIR = os.path.join(BASE, 'incoming')
PROCESSED_DIR = os.path.join(INCOMING_DIR, 'processed')
FORECLOSURES_JSON = os.path.join(REIFLOW_DIR, 'reiflow_foreclosures.json')
SOURCE_LABEL = 'DealSauce Nightly Pull'
ID_PREFIX = 'FC-DS'


def parse_row(row, idx):
    fn = row.get('FirstName', '').strip()
    ln = row.get('LastName', '').strip()
    owner = f"{fn} {ln}".strip() or row.get('Contact1Name', '').strip() or 'Unknown'

    prop_addr = row.get('PropertyAddress', '').strip()
    city = row.get('PropertyCity', '').strip()
    state = row.get('PropertyState', '').strip()
    zip_ = row.get('PropertyPostalCode', '').strip()
    full_addr = ', '.join(filter(None, [prop_addr, city, state, zip_]))

    prop_type = row.get('PropertyType', 'SFR').strip()
    if 'multi' in prop_type.lower() or 'MF' in prop_type:
        prop_type = 'Multi-Family'
    elif not prop_type:
        prop_type = 'SFR'

    phones = []
    for c in ['1', '2', '3']:
        for p in ['1', '2', '3']:
            ph = row.get(f'Contact{c}Phone_{p}', '').strip()
            dnc = row.get(f'Contact{c}Phone_{p}_DNC', '').strip().lower()
            lit = row.get(f'Contact{c}Phone_{p}_Litigator', '').strip().lower()
            if ph and dnc != 'true' and lit != 'true' and ph not in phones:
                phones.append(ph)
                if len(phones) >= 3:
                    break
        if len(phones) >= 3:
            break

    email = ''
    for c in ['1', '2', '3']:
        for e in ['1', '2', '3']:
            em = row.get(f'Contact{c}Email_{e}', '').strip()
            if em:
                email = em
                break
        if email:
            break

    status = 'Not Contacted' if phones else 'Need Skip Trace'

    avm_raw = row.get('AVM', '').replace('$', '').replace(',', '').strip()
    loan_raw = row.get('EstimatedMortgageBalance', '').replace('$', '').replace(',', '').strip()
    avm = float(avm_raw) if avm_raw.replace('.', '').isdigit() else 0
    loan = float(loan_raw) if loan_raw.replace('.', '').isdigit() else 0
    equity = max(0, avm - loan)

    high_eq = row.get('HighEquity', '').strip()
    free_clear = row.get('FreeAndClear', '').strip()
    pre_fc = row.get('PreForeclosure', '').strip()

    notes_parts = []
    if high_eq == '1':
        notes_parts.append('High Equity')
    if free_clear == '1':
        notes_parts.append('Free & Clear')
    if pre_fc == '1':
        notes_parts.append('Pre-Foreclosure')
    auction = row.get('AuctionDate', '').strip()
    if auction:
        notes_parts.append(f'Auction: {auction}')

    return {
        'id': f'{ID_PREFIX}-{idx:05d}',
        'type': 'foreclosure',
        'propType': prop_type,
        'owner': owner,
        'phone': phones[0] if len(phones) > 0 else '',
        'phone2': phones[1] if len(phones) > 1 else '',
        'phone3': phones[2] if len(phones) > 2 else '',
        'email': email,
        'address': prop_addr or full_addr,
        'fullAddress': full_addr,
        'source': SOURCE_LABEL,
        'listPrice': 0,
        'askingPrice': 0,
        'notes': ' | '.join(notes_parts),
        'status': status,
        'importedAt': date.today().isoformat(),
        'excess': 0,
        'cut': 0,
        'county': f"{city}, {state}",
        'loanBal': loan,
        'estValue': avm,
        'equity': equity,
    }


def main():
    os.makedirs(INCOMING_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    csv_files = sorted(
        f for f in os.listdir(INCOMING_DIR)
        if f.lower().endswith('.csv') and os.path.isfile(os.path.join(INCOMING_DIR, f))
    )

    existing = []
    if os.path.exists(FORECLOSURES_JSON):
        with open(FORECLOSURES_JSON) as f:
            existing = json.load(f)

    existing_addresses = {l.get('fullAddress', '').strip().lower() for l in existing if l.get('fullAddress')}
    max_idx = 0
    for l in existing:
        m = re.match(rf'{ID_PREFIX}-(\d+)$', l.get('id', ''))
        if m:
            max_idx = max(max_idx, int(m.group(1)))

    new_leads = []
    total_rows = 0
    dupes = 0
    idx = max_idx + 1

    for fname in csv_files:
        fpath = os.path.join(INCOMING_DIR, fname)
        try:
            with open(fpath, encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_rows += 1
                    lead = parse_row(row, idx)
                    addr_key = lead['fullAddress'].strip().lower()
                    if not addr_key or addr_key in existing_addresses:
                        dupes += 1
                        continue
                    existing_addresses.add(addr_key)
                    new_leads.append(lead)
                    idx += 1
        except Exception as e:
            print(f"WARN: failed to parse {fname}: {e}", file=sys.stderr)
            continue
        # archive processed file
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        shutil.move(fpath, os.path.join(PROCESSED_DIR, f'{ts}-{fname}'))

    merged = new_leads + existing
    with open(FORECLOSURES_JSON, 'w') as f:
        json.dump(merged, f)

    summary = {
        'csvFilesProcessed': len(csv_files),
        'totalRowsRead': total_rows,
        'duplicatesSkipped': dupes,
        'newLeadsAdded': len(new_leads),
        'totalForeclosureLeads': len(merged),
    }
    print('SUMMARY_JSON:' + json.dumps(summary))


if __name__ == '__main__':
    main()
