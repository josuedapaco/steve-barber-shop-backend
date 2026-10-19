import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

ROOT = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ROOT / 'app/catalog.json').read_text())
BARBERS, SERVICES = CATALOG['barbers'], CATALOG['services']
SERVICE_MAP = {s['id']: s for s in SERVICES}
NY = ZoneInfo('America/New_York')
def opening_hours(day):
    return (9*60, 17*60) if Date.fromisoformat(day).weekday() == 6 else (8*60+30, 19*60)

def booking_times(day):
    opening, closing = opening_hours(day)
    return [f'{value//60:02}:{value%60:02}' for value in range(opening, closing, 30)]
COOKIE = 'atelier_staff'

def today(): return datetime.now(NY).date().isoformat()
def now(): return datetime.now().isoformat()
def minutes(value):
    h, m = map(int, value.split(':'))
    return h*60+m

def valid_date(value):
    try: return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)) and Date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError): return False

def fail(status, message): raise HTTPException(status_code=status, detail=message)

@contextmanager
def database(write=False):
    path = Path(os.environ.get('DATABASE_PATH', './data/barber.sqlite'))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=5000')
    try:
        if write: conn.execute('BEGIN IMMEDIATE')
        yield conn
        if write: conn.commit()
    except BaseException:
        if write: conn.rollback()
        raise
    finally: conn.close()

def migrate():
    with database() as db: db.execute('PRAGMA journal_mode=WAL')
    with database(True) as db:
        # Keep the existing migration ledger so Node-created volumes remain compatible.
        db.execute('CREATE TABLE IF NOT EXISTS node_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
        for path in sorted((ROOT/'drizzle').glob('*.sql')):
            if db.execute('SELECT name FROM node_migrations WHERE name=?', (path.name,)).fetchone(): continue
            for statement in path.read_text().split(';'):
                if statement.strip(): db.execute(statement)
            db.execute('INSERT INTO node_migrations VALUES (?,?)', (path.name, now()))

@asynccontextmanager
async def lifespan(app):
    if not os.environ.get('STAFF_PIN', '').strip(): raise RuntimeError('STAFF_PIN must not be empty')
    migrate()
    yield

app = FastAPI(title='Steve Barber Shop API', version='2.0.0', lifespan=lifespan)

@app.exception_handler(HTTPException)
async def http_error(request, error): return JSONResponse({'error': error.detail}, status_code=error.status_code)
@app.exception_handler(RequestValidationError)
async def validation_error(request, error): return JSONResponse({'error': 'Please check your request details.'}, status_code=400)
@app.exception_handler(sqlite3.Error)
async def database_error(request, error): return JSONResponse({'error': 'Service temporarily unavailable.'}, status_code=503)

class RequestPolicy:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        origin = headers.get(b'origin', b'').decode()
        expected = os.environ.get('PUBLIC_ORIGIN', 'https://stevesbarbershopny.com')
        if scope['method'] not in ('GET', 'HEAD', 'OPTIONS') and origin and origin != expected:
            return await JSONResponse({'error': 'Origin not allowed'}, status_code=403)(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect': return
            body.extend(message.get('body', b''))
            if len(body) > 65536: return await JSONResponse({'error': 'Request too large'}, status_code=413)(scope, receive, send)
            if not message.get('more_body'): break
        delivered = False
        async def buffered():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        async def secured(message):
            if message['type'] == 'http.response.start':
                message['headers'] += [(b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff')]
            await send(message)
        await self.app(scope, buffered, secured)
app.add_middleware(RequestPolicy)

def all_team(db):
    seeds = {b['id']: b for b in BARBERS}
    people = [dict(b) for b in BARBERS]
    for row in db.execute('SELECT id,name FROM team_members ORDER BY created_at,id'):
        people.append(dict(row, image='/barber-avatar.svg', initials=''.join(w[0] for w in row['name'].split()[:2]).upper(), role='Barber'))
    settings = {r['staff_id']: json.loads(r['service_ids']) for r in db.execute('SELECT * FROM staff_service_settings')}
    for person in people:
        ids = settings.get(person['id'], list(SERVICE_MAP) if person['id'] in seeds else [])
        if not isinstance(ids, list) or any(not isinstance(i, str) or i not in SERVICE_MAP for i in ids) or len(set(ids)) != len(ids): fail(503, 'Invalid staff service configuration')
        person.update(staffId=person['id'], specialty='barber', serviceIds=ids)
    return people

def find_person(db, ident):
    person = next((p for p in all_team(db) if p['id'] == ident), None)
    if not person: fail(400, 'Invalid barber')
    return person

def authorized(db, ident, service):
    if service not in find_person(db, ident)['serviceIds']: fail(403, 'This professional is not authorized for this service.')

def key_for(db, role, subject):
    if role == 'manager': return os.environ.get('STAFF_PIN', '')
    if any(b['id'] == subject for b in BARBERS): return os.environ.get('BARBER_PIN_'+subject.upper(), '')
    row = db.execute('SELECT session_secret FROM team_members WHERE id=?', (subject,)).fetchone()
    return row['session_secret'] if row else ''

def digest(payload, key): return hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
def session(request: Request):
    try:
        role, subject, expires, signature = request.cookies.get(COOKIE, '').split('.')
        if role not in ('manager', 'barber') or (role == 'manager' and subject != 'all') or int(expires) <= time.time()*1000: raise ValueError()
        if not re.fullmatch(r'[\w-]{1,80}', subject, flags=re.ASCII): raise ValueError()
        with database() as db: key = key_for(db, role, subject)
        if not key or not hmac.compare_digest(digest(f'{role}.{subject}.{expires}', key), signature): raise ValueError()
        return {'role': role, 'barberId': subject if role == 'barber' else None}
    except (ValueError, TypeError): fail(401, 'Unauthorized')
def manager(user=Depends(session)):
    if user['role'] != 'manager': fail(403, 'Manager access required')
    return user

class Input(BaseModel): model_config = ConfigDict(extra='ignore')
class Login(Input):
    pin: StrictStr = Field(max_length=64)
    barberId: StrictStr | None = None

@app.get('/api/health')
def health(): return {'status': 'ok'}
@app.get('/api/team')
def public_team():
    with database() as db: return {'team': all_team(db)}
@app.post('/api/staff/login')
def login(data: Login, response: Response):
    role, subject = ('barber', data.barberId) if data.barberId is not None else ('manager', 'all')
    with database() as db:
        key = key_for(db, role, subject)
        if role == 'barber' and not any(b['id'] == subject for b in BARBERS):
            row = db.execute('SELECT pin_salt,pin_hash FROM team_members WHERE id=?', (subject,)).fetchone()
            valid = bool(row) and hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', data.pin.encode(), row['pin_salt'].encode(), 100000).hex(), row['pin_hash'])
        else: valid = bool(key) and hmac.compare_digest(data.pin.encode(), key.encode())
    if not valid: fail(401, 'Incorrect access code.')
    payload = f'{role}.{subject}.{int(time.time()*1000)+12*60*60*1000}'
    response.set_cookie(COOKIE, payload+'.'+digest(payload, key), max_age=43200, httponly=True, secure=True, samesite='lax')
    return {'ok': True, 'session': {'role': role, 'barberId': subject if role == 'barber' else None}}
@app.post('/api/staff/logout')
def logout(response: Response):
    response.delete_cookie(COOKIE, httponly=True, secure=True, samesite='lax')
    return {'ok': True}

def row_json(row):
    return {re.sub(r'_([a-z])', lambda m:m[1].upper(), key): value for key,value in dict(row).items()}
@app.get('/api/appointments')
def appointments(date: str | None = None, barber: str = '', user=Depends(session)):
    date = date or today()
    if not valid_date(date): fail(400, 'Invalid date')
    with database() as db:
        if user['role'] == 'barber': barber = user['barberId']
        elif barber: find_person(db, barber)
        rows = db.execute('SELECT * FROM appointments WHERE date=?'+(' AND barber_id=?' if barber else '')+' ORDER BY time', (date, barber) if barber else (date,)).fetchall()
        return {'appointments': [row_json(r) for r in rows], 'session': user}

def check_schedule(date, barber, service):
    if not valid_date(date) or date < today() or service not in SERVICE_MAP or not barber: fail(400, 'Choose a valid barber, service and date.')
def past_time(date, time):
    current = datetime.now(NY)
    return date == current.date().isoformat() and minutes(time) <= current.hour*60+current.minute+30

def overlaps(rows, time, duration):
    return any(minutes(time) < minutes(r['time'])+r['duration'] and minutes(r['time']) < minutes(time)+duration for r in rows)
@app.get('/api/availability')
def availability(date: str = '', barber: str = '', service: str = ''):
    check_schedule(date, barber, service)
    with database() as db:
        authorized(db, barber, service)
        rows = db.execute("SELECT * FROM appointments WHERE date=? AND barber_id=? AND status!='cancelled'", (date,barber)).fetchall()
        duration = SERVICE_MAP[service]['duration']
        return {'slots': [t for t in booking_times(date) if minutes(t)+duration <= opening_hours(date)[1] and not past_time(date,t) and not overlaps(rows,t,duration)]}

class Booking(Input):
    barberId: StrictStr
    serviceId: StrictStr
    date: StrictStr
    time: StrictStr
    name: StrictStr = Field(min_length=2,max_length=80)
    email: StrictStr = Field(max_length=120)
    phone: StrictStr = Field(min_length=7,max_length=25)
    notes: StrictStr = Field(default='',max_length=500)
@app.post('/api/appointments', status_code=201)
def book(data: Booking):
    check_schedule(data.date,data.barberId,data.serviceId)
    service = SERVICE_MAP[data.serviceId]
    if data.time not in booking_times(data.date) or minutes(data.time)+service['duration']>opening_hours(data.date)[1] or len(data.name.strip())<2 or len(data.phone.strip())<7 or not re.fullmatch(r'\S+@\S+\.\S+',data.email.strip()): fail(400,'Please check your reservation details.')
    if past_time(data.date,data.time): fail(409,'That time is no longer available.')
    try:
        with database(True) as db:
            authorized(db,data.barberId,data.serviceId)
            rows = db.execute("SELECT * FROM appointments WHERE date=? AND barber_id=? AND status!='cancelled'",(data.date,data.barberId)).fetchall()
            if overlaps(rows,data.time,service['duration']): fail(409,'That time was just taken. Please choose another.')
            ident = str(uuid.uuid4())
            db.execute('INSERT INTO appointments (id,barber_id,service_id,date,time,duration,customer_name,customer_email,customer_phone,notes,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(ident,data.barberId,data.serviceId,data.date,data.time,service['duration'],data.name.strip(),data.email.strip(),data.phone.strip(),data.notes.strip(),'confirmed',now()))
            for offset in range(0,service['duration'],15):
                value = minutes(data.time)+offset
                db.execute('INSERT INTO occupied_slots VALUES (?,?,?,?)',(data.barberId,data.date,f'{value//60:02}:{value%60:02}',ident))
        return dict(id=ident,date=data.date,time=data.time,barberId=data.barberId,serviceId=data.serviceId)
    except sqlite3.IntegrityError: fail(409,'That time was just taken. Please choose another.')
class Status(Input):
    id: StrictStr
    status: StrictStr
@app.post('/api/staff/status')
def update_status(data: Status,user=Depends(session)):
    if data.status not in ('completed','cancelled'): fail(400,'Invalid update')
    with database(True) as db:
        row = db.execute('SELECT * FROM appointments WHERE id=?',(data.id,)).fetchone()
        if not row: fail(404,'Appointment not found.')
        if user['role']=='barber' and row['barber_id']!=user['barberId']: fail(403,'You can only update your own appointments.')
        if row['status'] != 'confirmed': fail(409,'This appointment is already closed.')
        db.execute('UPDATE appointments SET status=? WHERE id=?',(data.status,data.id))
        if data.status=='cancelled': db.execute('DELETE FROM occupied_slots WHERE appointment_id=?',(data.id,))
    return {'ok':True}
class Assignment(Input):
    staffId: StrictStr
    serviceIds: list[StrictStr]
def validate_services(ids):
    if len(set(ids))!=len(ids) or any(s not in SERVICE_MAP for s in ids): fail(400,'Choose valid services from the barber menu.')
def save_services(db,staff_id,ids):
    db.execute('INSERT INTO staff_service_settings VALUES (?,?,?,?) ON CONFLICT(staff_id) DO UPDATE SET specialty=excluded.specialty,service_ids=excluded.service_ids,updated_at=excluded.updated_at',(staff_id,'barber',json.dumps(ids),now()))
@app.get('/api/staff/services')
def staff_services(user=Depends(manager)):
    with database() as db:return {'team':all_team(db)}
@app.post('/api/staff/services')
def assign(data:Assignment,user=Depends(manager)):
    validate_services(data.serviceIds)
    with database(True) as db:
        find_person(db,data.staffId)
        save_services(db,data.staffId,data.serviceIds)
        return {'ok':True,'team':all_team(db)}
class NewPerson(Input):
    name: StrictStr=Field(min_length=2,max_length=80)
    serviceIds:list[StrictStr]
    accessCode:StrictStr=Field(min_length=8,max_length=64)
@app.post('/api/staff/team',status_code=201)
def add_person(data:NewPerson,user=Depends(manager)):
    name=' '.join(data.name.split())
    if len(name)<2 or re.search(r'[\x00-\x1f\x7f]',data.name) or not data.accessCode.strip():fail(400,'Enter a valid name and personal access code.')
    validate_services(data.serviceIds)
    try:
        with database(True) as db:
            if any(p['name'].lower()==name.lower() for p in all_team(db)):fail(409,'A professional with this name already exists.')
            ident,salt=str(uuid.uuid4()),str(uuid.uuid4())
            hashed=hashlib.pbkdf2_hmac('sha256',data.accessCode.encode(),salt.encode(),100000).hex()
            db.execute('INSERT INTO team_members VALUES (?,?,?,?,?,?,?)',(ident,name,name.lower(),salt,hashed,str(uuid.uuid4()),now()))
            save_services(db,ident,data.serviceIds)
            return {'id':ident,'team':all_team(db)}
    except sqlite3.IntegrityError:fail(409,'A professional with this name already exists.')
@app.get('/api/staff/dashboard')
def dashboard(user=Depends(manager)):
    with database() as db:rows=[row_json(r) for r in db.execute('SELECT * FROM appointments ORDER BY date,time')]
    start=Date.fromisoformat(today());start-=timedelta(days=start.weekday())
    week=[dict(date=(start+timedelta(days=i)).isoformat(),reserved=0,completed=0,cancelled=0) for i in range(7)]
    clients={}
    for row in rows:
        price=SERVICE_MAP.get(row['serviceId'],{}).get('price',0)
        day=next((d for d in week if d['date']==row['date']),None)
        if day:
            bucket={'confirmed':'reserved','completed':'completed','cancelled':'cancelled'}.get(row['status'])
            if bucket:day[bucket]+=price
        key=row['customerEmail'].strip().lower()
        client=clients.setdefault(key,dict(name=row['customerName'],email=row['customerEmail'],phone=row['customerPhone'],visits=[],upcoming=[]))
        if row['status']=='completed':client['visits'].append(row)
        if row['status']=='confirmed' and row['date']>=today():client['upcoming'].append(row)
    for client in clients.values():
        client['visits'].sort(key=lambda r:(r['date'],r['time']),reverse=True)
        client['upcoming'].sort(key=lambda r:(r['date'],r['time']))
    demand=[]
    for service in SERVICES:
        bookings=[r for r in rows if r['serviceId']==service['id'] and r['status'] in ('confirmed','completed')]
        demand.append(dict(id=service['id'],name=service['name'],count=len(bookings),completed=sum(r['status']=='completed' for r in bookings),reserved=sum(r['status']=='confirmed' for r in bookings)))
    demand.sort(key=lambda s:(-s['count'],s['name']))
    return dict(week=week,serviceDemand=demand,totalRequests=sum(s['count'] for s in demand),clients=sorted(clients.values(),key=lambda c:c['name']))
