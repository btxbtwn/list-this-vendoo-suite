"""Read/invoke current code against a disposable database, with no live extension."""
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

root = Path(__file__).parent
with tempfile.TemporaryDirectory(prefix="vendoo-audit-probes-") as tmp:
    os.environ["VENDOO_STUDIO_DATA_DIR"] = tmp
    from fastapi.testclient import TestClient
    from PIL import Image
    from vendoo_studio.database import init_db
    from vendoo_studio.main import app
    from vendoo_studio.routes.extension import ExtensionManager
    init_db()
    client = TestClient(app, raise_server_exceptions=False)
    result = []
    def record(name, **data):
        result.append({"probe": name, **data})
    a = client.post('/api/conversations', json={"title": "Audit A"}).json()['id']
    b = client.post('/api/conversations', json={"title": "Audit B"}).json()['id']
    with patch('vendoo_studio.routes.chat.get_listing_provider', return_value=None):
        r = client.post(f'/api/conversations/{a}/messages', json={"text": "Recover this audit prompt"})
        record('missing provider prompt persistence', status=r.status_code, response=r.text,
               messages=client.get(f'/api/conversations/{a}/messages').json())
    listing = json.loads((root/'approved-studio-snapshot.json').read_text())['listing']
    r = client.put(f'/api/conversations/{a}/listing', json={"listing": listing})
    rev = client.get(f'/api/conversations/{a}/listing').json()['current_revision_id']
    r = client.post(f'/api/conversations/{b}/revisions/{rev}/restore')
    record('cross conversation revision restore', status=r.status_code,
           copied=client.get(f'/api/conversations/{b}/listing').json().get('listing',{}).get('title')==listing['title'])
    broken = {**listing, 'ebay_specifics': 'invalid'}
    r = client.put(f'/api/conversations/{a}/listing', json={"listing": broken})
    readback = client.get(f'/api/conversations/{a}/listing')
    record('invalid typed JSON poisons listing', put_status=r.status_code, get_status=readback.status_code)
    img = io.BytesIO()
    Image.new('RGB',(2,2),'white').save(img,format='PNG')
    r=client.post(f'/api/conversations/{b}/photos',files=[('files',('valid.png',img.getvalue(),'image/png')),('files',('invalid.txt',b'not an image','text/plain'))])
    record('partial upload',status=r.status_code,response=r.text,stored_count=len(client.get(f'/api/conversations/{b}/photos').json()))
    r=client.post(f'/api/conversations/{b}/photos',files=[('files',('../../audit-fake.jpg',b'not an image','image/jpeg'))])
    record('spoofed image MIME and traversal filename',status=r.status_code,response=r.json(),escaped_file=Path(tmp).parent.joinpath('audit-fake.jpg').exists())
    r=client.post(f'/api/conversations/{b}/photos',files=[('files',('oversize.jpg',b'x'*(21*1024*1024),'image/jpeg'))])
    record('oversize upload',status=r.status_code,response=r.text)
    r=client.get('/api/photos/..%2F..%2Fetc%2Fpasswd')
    record('photo traversal read',status=r.status_code)
    record('pairing literal bypass',accepted=ExtensionManager().verify_token('direct'))
    r=client.options('/api/conversations',headers={'Origin':'https://untrusted.invalid','Access-Control-Request-Method':'POST'})
    record('untrusted CORS preflight',status=r.status_code,allow_origin=r.headers.get('access-control-allow-origin'))
    r=client.options('/api/conversations',headers={'Origin':'https://www.etsy.com','Access-Control-Request-Method':'POST'})
    record('marketplace CORS preflight',status=r.status_code,allow_origin=r.headers.get('access-control-allow-origin'))
    (root/'isolated-probes.json').write_text(json.dumps(result,indent=2))
    for item in result:
        print(json.dumps(item))
