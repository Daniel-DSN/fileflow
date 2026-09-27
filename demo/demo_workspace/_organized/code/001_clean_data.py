"""Demo ETL cleaner."""

def clean(rows):
    return [r.strip() for r in rows]
