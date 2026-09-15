from __future__ import annotations
import hashlib,shutil
from pathlib import Path
from typing import Any
from .config import ASSET_DIR,DB_PATH,DATA_DIR,TMP_DIR
from .db import db,now_iso

def _sha256(path:Path)->str:
    d=hashlib.sha256()
    with path.open('rb') as h:
        for chunk in iter(lambda:h.read(1024*1024),b''):d.update(chunk)
    return d.hexdigest()

def integrity_report(*,verify_checksums:bool=False)->dict[str,Any]:
    missing=[];size_mismatch=[];checksum_mismatch=[];referenced_paths=set();checked=0
    with db() as conn:
        rows=conn.execute("SELECT id,name,type,storage_path,size_bytes,checksum_sha256 FROM assets WHERE deleted_at IS NULL AND type IN ('image','video') ORDER BY created_at").fetchall()
        for row in rows:
            checked+=1;path_text=row['storage_path']
            if not path_text:missing.append({'id':row['id'],'name':row['name'],'type':row['type'],'reason':'no storage path'});continue
            path=Path(path_text).resolve();referenced_paths.add(path)
            if ASSET_DIR.resolve() not in path.parents or not path.is_file():missing.append({'id':row['id'],'name':row['name'],'type':row['type'],'path':str(path)});continue
            actual=path.stat().st_size;expected=row['size_bytes']
            if expected is not None and actual!=expected:size_mismatch.append({'id':row['id'],'name':row['name'],'expected':expected,'actual':actual})
            if verify_checksums and row['checksum_sha256']:
                actual_hash=_sha256(path)
                if actual_hash!=row['checksum_sha256']:checksum_mismatch.append({'id':row['id'],'name':row['name'],'expected':row['checksum_sha256'],'actual':actual_hash})
    orphan_files=[str(p) for p in sorted(ASSET_DIR.glob('*')) if p.is_file() and p.resolve() not in referenced_paths]
    temp_files=[str(p) for p in sorted(TMP_DIR.glob('*')) if p.is_file()];usage=shutil.disk_usage(DATA_DIR);issues=len(missing)+len(size_mismatch)+len(checksum_mismatch)
    return {'ok':issues==0,'checked_at':now_iso(),'database':str(DB_PATH),'asset_dir':str(ASSET_DIR),'local_assets_checked':checked,'image_assets_checked':checked,'missing_assets':missing,'size_mismatch':size_mismatch,'checksum_mismatch':checksum_mismatch,'orphan_files':orphan_files,'temp_files':temp_files,'disk':{'total':usage.total,'used':usage.used,'free':usage.free}}
