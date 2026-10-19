"""Explicitly import compatible SQLite data into an empty target; never overwrite."""
import os
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.main import migrate, database
if len(sys.argv)!=2: raise SystemExit('Usage: python scripts/import_data.py /path/to/previous.sqlite')
source=Path(sys.argv[1]).resolve()
target=Path(os.environ.get('DATABASE_PATH','./data/barber.sqlite')).resolve()
if not source.is_file() or source==target:raise SystemExit('Source must be an existing, different SQLite file')
migrate()
with database(True) as db:
    tables=['appointments','occupied_slots','team_members','staff_service_settings']
    if any(db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables):raise SystemExit('Target contains data; nothing was imported')
    db.execute('ATTACH DATABASE ? AS previous',(source.as_uri()+'?mode=ro',))
    for table in tables:
        if db.execute("SELECT name FROM previous.sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():db.execute(f'INSERT INTO main.{table} SELECT * FROM previous.{table}')
    print('Imported appointments:',db.execute('SELECT count(*) FROM appointments').fetchone()[0])
