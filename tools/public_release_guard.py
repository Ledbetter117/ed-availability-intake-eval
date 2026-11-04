"""Public-release mechanical checks; not a security or PR certification.

Scan exact Git objects, including staged bytes with --index. Deliberate manual
review records bind every file except their own receipt and a separately checked
integrity manifest. No network access, model calls, or matched secret output.
"""
from __future__ import annotations
import argparse, hashlib, io, json, re, subprocess, sys, zipfile
from datetime import date
from pathlib import Path, PurePosixPath

RECEIPT = '.public-release-review.json'
MAX_FILE = 25 * 1024 * 1024
TEXT = {'.md','.txt','.json','.csv','.yml','.yaml','.toml','.py','.html','.css','.js','.cff','.xml','.svg','.ps1','.cmd','.bat'}
FORBIDDEN_KEYS = {'/JavaScript','/JS','/Launch','/EmbeddedFiles','/RichMedia','/SubmitForm','/ImportData'}

def git(root, *args):
    return subprocess.run(['git','-C',str(root),*args],capture_output=True,check=True).stdout

def inventory(root, index=False, ref='HEAD'):
    rows={}
    raw=git(root,'ls-files','--stage','-z') if index else git(root,'ls-tree','-rz','--full-tree',ref)
    for line in raw.split(b'\0'):
        if not line: continue
        meta,path=line.split(b'\t',1);parts=meta.decode().split()
        mode,oid,stage=(parts[0],parts[1],parts[2]) if index else (parts[0],parts[2],'0')
        if stage!='0':raise ValueError('Unmerged index entry')
        name=path.decode('utf-8','strict')
        if mode not in ('100644','100755'):raise ValueError('Unsupported symlink/submodule: '+name)
        size=int(git(root,'cat-file','-s',oid))
        if size>MAX_FILE:raise ValueError('File exceeds inspected size boundary: '+name)
        rows[name]=git(root,'cat-file','blob',oid)
    if not rows:raise ValueError('Empty public inventory')
    return rows

def fingerprint(rows):
    return {n:hashlib.sha256(b).hexdigest() for n,b in sorted(rows.items()) if n not in {RECEIPT,'MANIFEST.json'}}

def inspect(rows, require_review=True):
    errors=[];warnings=[];font_reviews=[];stats={'files':len(rows),'pdf_pages':0,'images':0,'archives':0}
    def fail(path,rule):errors.append({'path':path,'rule':rule})
    for name,data in rows.items():
        p=PurePosixPath(name);suffix=p.suffix.lower()
        actual=None
        if b'%PDF-' in data[:1024]:actual='.pdf'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):actual='.png'
        elif data.startswith(b'\xff\xd8\xff'):actual='.jpg'
        elif data.startswith((b'PK\x03\x04',b'PK\x05\x06',b'PK\x07\x08')):actual='.zip'
        elif data.startswith((b'\x00\x01\x00\x00',b'OTTO')):actual='.ttf'
        if actual and suffix!=actual and not (actual=='.jpg' and suffix=='.jpeg') and not (actual=='.ttf' and suffix=='.otf') and not (actual=='.zip' and suffix in {'.docx','.xlsx','.pptx'}):fail(name,'format_extension_mismatch')
        if actual:suffix=actual
        if suffix not in TEXT|{'.pdf','.png','.jpg','.jpeg','.webp','.tif','.tiff','.avif','.zip','.docx','.xlsx','.pptx','.tar','.gz','.7z','.rar','.ttf','.otf'}:
            try:
                decoded=data.decode('utf-8-sig')
                if '\x00' in decoded:raise ValueError('binary')
                suffix='.txt'
            except (UnicodeDecodeError,ValueError):fail(name,'unsupported_binary_format')
        if p.is_absolute() or '..' in p.parts or '\\' in name:fail(name,'unsafe_public_path')
        if any(x in {'.env','.aws','.ssh','.qa-review','private-preimages','__pycache__'} for x in p.parts):fail(name,'private_or_runtime_path')
        if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',data):fail(name,'private_key_material')
        if b'PUBLIC_RELEASE_'+b'PRIVATE_CANARY' in data:fail(name,'private_canary')
        if data.startswith(b'version https://git-lfs.github.com/spec/'):fail(name,'lfs_object_not_inspected')
        if suffix in TEXT or p.name in {'LICENSE','.gitignore','.gitattributes'}:
            try:text=data.decode('utf-8-sig')
            except UnicodeDecodeError:fail(name,'unreadable_text');continue
            # Locations only; never log the matched personal path or credential.
            if re.search(r'(?i)\b[A-Z]:[\\/]+Users[\\/]+(?!<|YOUR_|USERNAME|example)[A-Za-z0-9_.-]+',text):fail(name,'personal_host_path')
            if re.search(r'(?i)https?://[^\s/:@]+:[^\s/@]+@',text):fail(name,'credential_in_url')
            if p.name in {'README.md','LINKEDIN-DRAFT.md','RELEASE-NOTES.md'} and re.search(r'(?i)\b(guaranteed safe|airtight|zero[- ]risk|100% secure|clinically validated)\b',text):
                warnings.append({'path':name,'rule':'contextual_claim_review_required'})
        if suffix in {'.yml','.yaml'} and name.startswith('.github/workflows/'):
            text=data.decode('utf-8-sig')
            try:
                import yaml
                class UniqueLoader(yaml.SafeLoader):pass
                def mapping(loader,node,deep=False):
                    result={}
                    for key_node,value_node in node.value:
                        key=loader.construct_object(key_node,deep=deep)
                        if key in result:raise ValueError('duplicate YAML key')
                        result[key]=loader.construct_object(value_node,deep=deep)
                    return result
                UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
                document=yaml.load(text,Loader=UniqueLoader)
                events=document.get('on',document.get(True,{}))
                if isinstance(events,str):events=[events]
                if 'pull_request_target' in events:fail(name,'privileged_contribution_event')
                permissions=document.get('permissions')
                if not isinstance(permissions,dict) or permissions.get('contents')!='read' or 'write' in permissions.values():fail(name,'missing_read_only_default_permissions')
                for job in document.get('jobs',{}).values():
                    jp=job.get('permissions',{})
                    if not isinstance(jp,dict) or 'write' in jp.values():fail(name,'privileged_job_permissions')
                    for step in [job]+job.get('steps',[]):
                        use=step.get('uses')
                        if use and not use.startswith('./') and not re.fullmatch(r'[^@]+@[0-9a-f]{40}',use):fail(name,'mutable_action_reference')
                        if re.search(r'\$\{\{\s*github\.event\.(?:pull_request|issue|comment|discussion)',str(step.get('run',''))):fail(name,'untrusted_inline_workflow_expression')
            except Exception as exc:fail(name,'workflow_parse_unavailable_or_failed:'+type(exc).__name__)
        if suffix=='.pdf':
            try:
                from pypdf import PdfReader
                from pypdf.generic import DictionaryObject, ArrayObject, IndirectObject
                reader=PdfReader(io.BytesIO(data),strict=True)
                if reader.is_encrypted:raise ValueError('encrypted PDF')
                stats['pdf_pages']+=len(reader.pages)
                seen=set();stack=[reader.trailer];count=0
                while stack:
                    obj=stack.pop();count+=1
                    if count>100000:raise ValueError('PDF object limit')
                    if isinstance(obj,IndirectObject):
                        key=(obj.idnum,obj.generation)
                        if key in seen:continue
                        seen.add(key);obj=obj.get_object()
                    if isinstance(obj,DictionaryObject):
                        if FORBIDDEN_KEYS.intersection(obj.keys()):fail(name,'active_or_embedded_pdf_content')
                        if obj.get('/S') in ('/JavaScript','/Launch','/GoToR','/SubmitForm','/ImportData'):fail(name,'unsafe_pdf_action')
                        if '/URI' in obj:
                            uri=str(obj['/URI'])
                            if uri.startswith('http://'):warnings.append({'path':name,'rule':'unencrypted_pdf_link_review'})
                            elif not uri.startswith(('https://','mailto:','#')):fail(name,'unsafe_pdf_link_scheme')
                        stack.extend(obj.values())
                    elif isinstance(obj,ArrayObject):stack.extend(obj)
                metadata=str(reader.metadata or {})
                if re.search(r'(?i)([A-Z]:[\\/]+Users[\\/]|/Users/|/home/)',metadata):fail(name,'private_pdf_metadata')
                for page in reader.pages:
                    if re.search(r'(?i)[A-Z]:[\\/]+Users[\\/]',page.extract_text() or ''):fail(name,'personal_path_in_pdf')
            except Exception as exc:fail(name,'pdf_check_unavailable_or_failed:'+type(exc).__name__)
        elif suffix in {'.png','.jpg','.jpeg','.webp','.tif','.tiff','.avif'}:
            try:
                from PIL import Image
                image=Image.open(io.BytesIO(data));image.verify()
                image=Image.open(io.BytesIO(data));stats['images']+=1
                exif=image.getexif()
                if exif or image.info.get('exif'):fail(name,'image_metadata_requires_specific_review')
                if any(k.lower() in {'gps','author','artist','comment','description'} for k in image.info):fail(name,'image_personal_metadata_candidate')
            except Exception as exc:fail(name,'image_check_unavailable_or_failed:'+type(exc).__name__)
        elif suffix=='.svg':
            text=data.decode('utf-8-sig')
            if re.search(r'(?i)<!DOCTYPE|<!ENTITY|<\s*script\b|<\s*foreignObject\b|\bon\w+\s*=|(?:href|src)\s*=\s*[\"\x27]\s*(?:javascript:|data:|file:|https?://)',text):fail(name,'active_or_external_svg_content')
        elif suffix in {'.ttf','.otf'}:
            if actual!='.ttf':fail(name,'font_format_unverified')
            font_reviews.append(name)
            warnings.append({'path':name,'rule':'font_requires_recorded_source_license_review'})
        elif suffix in {'.zip','.docx','.xlsx','.pptx','.tar','.gz','.7z','.rar'}:
            stats['archives']+=1
            # Generic release route does not silently certify nested or encrypted content.
            fail(name,'archive_requires_separate_reviewed_export')
    if 'MANIFEST.json' in rows:
        try:
            manifest=json.loads(rows['MANIFEST.json'])
            entries=manifest['files'];paths=[e['path'] for e in entries]
            if len(paths)!=len(set(paths)) or set(paths)!=set(rows)-{'MANIFEST.json'}:raise ValueError('Manifest coverage mismatch')
            if any(hashlib.sha256(rows[e['path']]).hexdigest()!=e['sha256'] for e in entries):raise ValueError('Manifest hash mismatch')
        except Exception:fail('MANIFEST.json','integrity_manifest_invalid')
    # Exceptions are exact-file, exact-rule, hash-bound and dated; no broad test exclusion.
    if '.public-release-exceptions.json' in rows:
        try:
            exceptions=json.loads(rows['.public-release-exceptions.json'])['exceptions']
            for item in exceptions:
                if item['path'] not in rows or hashlib.sha256(rows[item['path']]).hexdigest()!=item['sha256'] or date.fromisoformat(item['expires'])<date.today() or not item.get('reason'):raise ValueError('Invalid exception')
                matched=[e for e in errors if e['path']==item['path'] and e['rule']==item['rule']]
                if not matched:raise ValueError('Stale exception')
                for e in matched:errors.remove(e);warnings.append(dict(e,exception_reason=item['reason']))
        except Exception:fail('.public-release-exceptions.json','invalid_or_stale_exception')
    if require_review:
        try:
            record=json.loads(rows[RECEIPT])
            if record.get('schema')!='public-release-review/2' or record.get('verdict')!='accepted_with_documented_limits':raise ValueError('review verdict missing')
            if record.get('files')!=fingerprint(rows):raise ValueError('review content changed')
            if record.get('integrity_manifests')!=(['MANIFEST.json'] if 'MANIFEST.json' in rows else []):raise ValueError('integrity manifest presence changed')
            if any(not record.get('font_source_reviews',{}).get(name) for name in font_reviews):raise ValueError('font source review missing')
            if not record.get('reviewers') or not record.get('limitations') or not record.get('reviewed_at'):raise ValueError('review evidence fields missing')
        except Exception:fail(RECEIPT,'missing_or_stale_substantive_review')
    return {'pass':not errors,'stats':stats,'errors':errors,'warnings':warnings,'limits':['Machine checks do not certify privacy, clinical validity, authorship, claim accuracy or exploit freedom.','PDF object/text checks and image metadata checks do not replace visual review.','GitHub settings, old releases, external sites and secret history require separate recorded checks.']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path.cwd());p.add_argument('--index',action='store_true');p.add_argument('--ref',default='HEAD');p.add_argument('--inventory',action='store_true');p.add_argument('--no-review',action='store_true',help='Diagnostic only; never use to authorize publication');a=p.parse_args()
    try:
        rows=inventory(a.root,a.index,a.ref)
        result={'files':fingerprint(rows)} if a.inventory else inspect(rows,not a.no_review)
        if a.no_review:result['diagnostic_only']=True
        print(json.dumps(result,indent=2));return 0 if a.inventory or result['pass'] else 1
    except Exception as exc:
        print(json.dumps({'pass':False,'failure':type(exc).__name__,'scope':'Inventory or required scanner failed; not a clean result'}));return 2

if __name__=='__main__':sys.exit(main())
