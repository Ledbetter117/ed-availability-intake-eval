import hashlib, io, json, unittest
from unittest.mock import patch
import public_release_guard as guard

def reviewed(rows):
    rows=dict(rows)
    rows[guard.RECEIPT]=json.dumps({'schema':'public-release-review/2','verdict':'accepted_with_documented_limits','reviewers':['synthetic test fixture, not an actual review'],'reviewed_at':'2026-11-03','limitations':['test fixture'],'integrity_manifests':['MANIFEST.json'] if 'MANIFEST.json' in rows else [],'files':guard.fingerprint(rows)}).encode()
    return rows

class GuardTests(unittest.TestCase):
    def test_clean(self):self.assertTrue(guard.inspect(reviewed({'README.md':b'Bounded software demonstration.'}))['pass'])
    def test_missing_review(self):self.assertFalse(guard.inspect({'README.md':b'x'})['pass'])
    def test_changed_byte(self):
        r=reviewed({'README.md':b'a'});r['README.md']=b'b';self.assertFalse(guard.inspect(r)['pass'])
    def test_omitted_file(self):
        r=reviewed({'README.md':b'a'});r['new.txt']=b'b';self.assertFalse(guard.inspect(r)['pass'])
    def test_canary(self):self.assertFalse(guard.inspect(reviewed({'a.txt':b'PUBLIC_RELEASE_'+b'PRIVATE_CANARY'}))['pass'])
    def test_key(self):self.assertFalse(guard.inspect(reviewed({'a.txt':b'-----BEGIN '+b'PRIVATE KEY-----'}))['pass'])
    def test_private_path(self):self.assertFalse(guard.inspect(reviewed({'a.txt':b'C:'+b'/Users/PrivatePerson/secret.txt'}))['pass'])
    def test_credential_url(self):self.assertFalse(guard.inspect(reviewed({'a.txt':b'https://' + b'user:password@example.org'}))['pass'])
    def test_private_filename(self):self.assertFalse(guard.inspect(reviewed({'.env':b'x'}))['pass'])
    def test_zip_closed(self):self.assertFalse(guard.inspect(reviewed({'a.zip':b'not even a readable archive'}))['pass'])
    def test_malformed_pdf(self):self.assertFalse(guard.inspect(reviewed({'a.pdf':b'invalid'}))['pass'])
    def test_missing_pdf_parser(self):
        with patch.dict('sys.modules',{'pypdf':None}):self.assertFalse(guard.inspect(reviewed({'a.pdf':b'%PDF-1.4'}))['pass'])
    def test_active_pdf(self):
        from pypdf import PdfWriter
        w=PdfWriter();w.add_blank_page(100,100);w.add_js('app.alert("synthetic control")');out=io.BytesIO();w.write(out)
        self.assertFalse(guard.inspect(reviewed({'a.pdf':out.getvalue()}))['pass'])
        self.assertFalse(guard.inspect(reviewed({'a.bin':out.getvalue()}))['pass'])
    def test_image_metadata(self):
        from PIL import Image,PngImagePlugin
        out=io.BytesIO();meta=PngImagePlugin.PngInfo();meta.add_text('Author','synthetic tester');Image.new('RGB',(2,2)).save(out,format='PNG',pnginfo=meta)
        self.assertFalse(guard.inspect(reviewed({'a.png':out.getvalue()}))['pass'])
    def test_active_svg(self):self.assertFalse(guard.inspect(reviewed({'a.svg':b'<svg><script>alert(1)</script></svg>'}))['pass'])
    def test_mutable_action(self):self.assertFalse(guard.inspect(reviewed({'.github/workflows/a.yml':b'permissions:\n  contents: read\njobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n'}))['pass'])
    def test_mutable_flow_action(self):self.assertFalse(guard.inspect(reviewed({'.github/workflows/a.yml':b'permissions: {contents: read}\njobs: {a: {steps: [{uses: actions/checkout@main}]}}'}))['pass'])
    def test_pinned_flow_action(self):
        workflow=b'permissions: {contents: read}\njobs: {a: {steps: [{uses: actions/checkout@'+b'a'*40+b'}]}}'
        self.assertTrue(guard.inspect(reviewed({'.github/workflows/a.yml':workflow}))['pass'])
    def test_unknown_binary(self):self.assertFalse(guard.inspect(reviewed({'a.bin':b'\x00\xff\xfe'}))['pass'])
    def test_privileged_event(self):self.assertFalse(guard.inspect(reviewed({'.github/workflows/a.yml':b'on:\n  pull_request_target:\npermissions:\n  contents: read\n'}))['pass'])
    def test_manifest_missing_item(self):self.assertFalse(guard.inspect(reviewed({'README.md':b'x','MANIFEST.json':b'{"files":[]}'}))['pass'])
    def test_manifest_deletion(self):
        r=reviewed({'README.md':b'x','MANIFEST.json':b''})
        r['MANIFEST.json']=json.dumps({'files':[{'path':n,'sha256':hashlib.sha256(b).hexdigest()} for n,b in r.items() if n!='MANIFEST.json']}).encode()
        self.assertTrue(guard.inspect(r)['pass']);del r['MANIFEST.json'];self.assertFalse(guard.inspect(r)['pass'])
    def test_exception_exact(self):
        data=b'https://' + b'user:password@example.org'
        r={'fixture.txt':data};r['.public-release-exceptions.json']=json.dumps({'exceptions':[{'path':'fixture.txt','sha256':hashlib.sha256(data).hexdigest(),'rule':'credential_in_url','reason':'Documented fake test credential','expires':'2099-01-01'}]}).encode()
        self.assertTrue(guard.inspect(reviewed(r))['pass'])
        r['fixture.txt']+=b'changed';self.assertFalse(guard.inspect(reviewed(r))['pass'])
    def test_stale_exception(self):
        r={'README.md':b'clean'};r['.public-release-exceptions.json']=json.dumps({'exceptions':[{'path':'README.md','sha256':hashlib.sha256(r['README.md']).hexdigest(),'rule':'credential_in_url','reason':'stale','expires':'2099-01-01'}]}).encode();self.assertFalse(guard.inspect(reviewed(r))['pass'])

if __name__=='__main__':unittest.main()
