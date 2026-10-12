from pathlib import Path
import json
path = Path(__file__).resolve().parents[1]/'web/data/current.json'
if path.exists():
    data = json.loads(path.read_text())
    print('# Price4PC collection\n')
    print('Updated:', data['updated_at'])
    print('\nOffers:', len(data['offers']))
    print('\n| Platform | Product | Status | Count |\n| --- | --- | --- | --- |')
    for row in data['statuses']:
        print(f"| {row['platform']} | {row.get('product_id', 'feed')} | {row['status']} | {row['count']} |")
    print('\nMissing prices stay empty. Source restrictions are reported, not fabricated.')
else:
    print('Collection did not produce an output file; inspect earlier steps.')
