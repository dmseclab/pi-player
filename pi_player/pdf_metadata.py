from pathlib import Path
from fastapi import HTTPException
from pypdf import PdfReader
from .config import ASSET_DIR
from .db import db


def count_pages(path: Path) -> int:
    try:
        with path.open('rb') as stream:
            reader=PdfReader(stream)
            if reader.is_encrypted:
                raise HTTPException(400,'Password protected PDFs are unsupported')
            count=len(reader.pages)
            if not 1 <= count <= 10000:
                raise HTTPException(400,'PDF must contain 1 to 10000 pages')
            return count
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400,'PDF could not be read') from exc


def populate_metadata(row: dict) -> dict:
    path=Path(row.get('storage_path') or '').resolve()
    if not path.is_file() or ASSET_DIR.resolve() not in path.parents:
        return row
    try:
        row['pdf_page_count']=count_pages(path)
        error=None
    except HTTPException as exc:
        error=str(exc.detail)
        row['pdf_metadata_error']=error
    with db() as conn:
        conn.execute('UPDATE assets SET pdf_page_count=?,pdf_metadata_error=? WHERE id=?',
                     (row.get('pdf_page_count'),error,row['id']))
    return row
