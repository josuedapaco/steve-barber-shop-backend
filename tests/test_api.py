from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import sqlite3
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app, database, migrate, SERVICES

BASE={'barberId':'marco','serviceId':'signature','date':'2099-06-15','time':'10:00','name':'Cliente Demo','email':'demo@example.com','phone':'2025550101'}
@pytest.fixture
def clients(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'test.sqlite'))
    monkeypatch.setenv('STAFF_PIN','manager-test-code')
    monkeypatch.setenv('BARBER_PIN_MARCO','marco-test-code')
    with TestClient(app,base_url='https://stevesbarbershopny.com') as public:
        manager=TestClient(app,base_url='https://stevesbarbershopny.com')
        assert manager.post('/api/staff/login',json={'pin':'manager-test-code'}).status_code==200
        barber=TestClient(app,base_url='https://stevesbarbershopny.com')
        assert barber.post('/api/staff/login',json={'pin':'marco-test-code','barberId':'marco'}).status_code==200
        yield public,manager,barber
        manager.close();barber.close()
def book(client,**changes):return client.post('/api/appointments',json={**BASE,**changes})
def slots(client,barber='marco',service='signature'):return client.get('/api/availability',params={'date':BASE['date'],'barber':barber,'service':service})

def test_public_catalog_and_health(clients):
    c,_,_=clients
    assert c.get('/api/health').json()=={'status':'ok'}
    team=c.get('/api/team').json()['team']
    assert len(team)==4
    assert team[0]['serviceIds']==[service['id'] for service in SERVICES]
    assert [p['name'] for p in team]==['David','Steve','Joey','Mike']
    assert 'pin' not in json.dumps(team).lower()

def test_booking_and_overlap(clients):
    c,m,_=clients
    assert '10:00' in slots(c).json()['slots']
    r=book(c);assert r.status_code==201
    assert book(c).status_code==409
    assert book(c,time='10:30').status_code==201
    assert book(c,time='11:00').status_code==201
    assert book(c,barberId='james').status_code==201
    assert '10:00' not in slots(c).json()['slots']
    rows=m.get('/api/appointments',params={'date':BASE['date']}).json()['appointments']
    assert len(rows)==4 and rows[0]['customerName']==BASE['name']
    with database() as db:assert db.execute('SELECT count(*) FROM occupied_slots WHERE appointment_id=?',(r.json()['id'],)).fetchone()[0]==2
@pytest.mark.parametrize('changes',[{'email':'invalid'},{'name':''},{'name':' '},{'phone':'123'},{'phone':'       '},{'date':'2000-01-01'},{'date':'2099-02-31'},{'date':'not-date'},{'barberId':'missing'},{'serviceId':'missing'},{'time':'19:00'},{'time':'19:30'},{'notes':'x'*501}])
def test_invalid_booking(clients,changes):assert book(clients[0],**changes).status_code==400

def test_duration_and_concurrency(clients):
    c,_,_=clients
    assert book(c,time='13:00',serviceId='complete').status_code==201
    assert book(c,time='13:30',serviceId='beard').status_code==409
    assert book(c,time='15:00',serviceId='beard').status_code==201
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:book(c,time='16:00').status_code,range(2)))
    assert sorted(results)==[201,409]
    with database() as db:assert db.execute("SELECT count(*) FROM appointments WHERE time='16:00'").fetchone()[0]==1

def test_private_access_and_roles(clients):
    c,m,b=clients
    ident=book(c,barberId='james').json()['id']
    assert c.get('/api/appointments').status_code==401
    assert b.get('/api/staff/dashboard').status_code==403
    assert b.get('/api/staff/services').status_code==403
    assert b.post('/api/staff/status',json={'id':ident,'status':'completed'}).status_code==403
    assert b.get('/api/appointments',params={'date':BASE['date'],'barber':'james'}).json()['appointments']==[]
    assert m.get('/api/appointments',params={'date':'2099-02-31'}).status_code==400

def test_cancellation_releases_slot(clients):
    c,m,_=clients
    ident=book(c).json()['id']
    assert m.post('/api/staff/status',json={'id':ident,'status':'cancelled'}).status_code==200
    assert '10:00' in slots(c).json()['slots']
    assert book(c).status_code==201
    assert m.post('/api/staff/status',json={'id':ident,'status':'completed'}).status_code==409

def test_dashboard_history(clients):
    c,m,_=clients
    ident=book(c).json()['id']
    assert m.post('/api/staff/status',json={'id':ident,'status':'completed'}).status_code==200
    data=m.get('/api/staff/dashboard').json()
    assert len(data['week'])==7 and data['totalRequests']==1
    assert data['clients'][0]['visits'][0]['id']==ident
    assert data['serviceDemand'][0]['id']=='signature'

def test_new_barber_lifecycle(clients):
    c,m,b=clients
    person={'name':'Barbero Nuevo','serviceIds':['beard'],'accessCode':'new-barber-code'}
    assert c.post('/api/staff/team',json=person).status_code==401
    assert b.post('/api/staff/team',json=person).status_code==403
    result=m.post('/api/staff/team',json=person);assert result.status_code==201
    ident=result.json()['id']
    assert len(result.json()['team'])==5
    assert m.post('/api/staff/team',json={**person,'name':' BARBERO  NUEVO '}).status_code==409
    assert m.post('/api/staff/team',json={**person,'name':'David'}).status_code==409
    with database() as db:
        row=db.execute('SELECT * FROM team_members WHERE id=?',(ident,)).fetchone()
        assert len(row['pin_hash'])==64 and row['pin_hash']!=person['accessCode']
    serialized=json.dumps(c.get('/api/team').json())
    for secret in ['pin_hash','pinHash','session_secret','sessionSecret',person['accessCode']]:assert secret not in serialized
    assert book(c,barberId=ident).status_code==403
    assert slots(c,ident).status_code==403
    assert book(c,barberId=ident,serviceId='beard').status_code==201
    with TestClient(app,base_url='https://stevesbarbershopny.com') as new:
        assert new.post('/api/staff/login',json={'pin':'incorrect','barberId':ident}).status_code==401
        assert new.post('/api/staff/login',json={'pin':person['accessCode'],'barberId':ident}).status_code==200
        rows=new.get('/api/appointments',params={'date':BASE['date'],'barber':'marco'}).json()['appointments']
        assert len(rows)==1 and all(r['barberId']==ident for r in rows)
        assert new.post('/api/staff/services',json={'staffId':ident,'serviceIds':[]}).status_code==403
    assert m.post('/api/staff/services',json={'staffId':ident,'serviceIds':['signature','beard','complete']}).status_code==200
    assert slots(c,ident).status_code==200
    assert m.post('/api/staff/services',json={'staffId':ident,'serviceIds':[]}).status_code==200
    assert book(c,barberId=ident,serviceId='beard',time='12:00').status_code==403
    assert len(m.get('/api/appointments',params={'date':BASE['date'],'barber':ident}).json()['appointments'])==1
@pytest.mark.parametrize('changes',[{'name':''},{'name':'x'*81},{'accessCode':'123'},{'accessCode':' '*8},{'serviceIds':['unknown']},{'serviceIds':['beard','beard']}])
def test_invalid_new_person(clients,changes):
    assert clients[1].post('/api/staff/team',json={'name':'Demo','serviceIds':['beard'],'accessCode':'demo-person-code',**changes}).status_code==400
@pytest.mark.parametrize('assignment',[{'staffId':'missing','serviceIds':[]},{'staffId':'marco','serviceIds':['beard','beard']},{'staffId':'marco','serviceIds':['unknown']}])
def test_invalid_assignment(clients,assignment):assert clients[1].post('/api/staff/services',json=assignment).status_code==400

def test_invalid_persisted_permissions_fail_closed(clients):
    c,m,_=clients
    m.post('/api/staff/services',json={'staffId':'marco','serviceIds':[]})
    with database(True) as db:db.execute("UPDATE staff_service_settings SET service_ids='[\"unknown\"]' WHERE staff_id='marco'")
    assert slots(c).status_code==503
    assert book(c).status_code==503

def test_request_policy(clients):
    c,_,_=clients
    assert c.post('/api/staff/login',headers={'Origin':'https://evil.example'},json={'pin':'manager-test-code'}).status_code==403
    assert c.post('/api/staff/login',content='x'*65537).status_code==413
    assert c.post('/api/staff/login',content='{',headers={'Content-Type':'application/json'}).status_code==400
    assert c.get('/api/health').headers['cache-control']=='no-store'

def test_compatible_node_session_and_database(clients):
    c,_,_=clients
    ident=book(c).json()['id']
    migrate()
    payload=f'manager.all.{int(time.time()*1000)+60000}'
    token=payload+'.'+hmac.new(b'manager-test-code',payload.encode(),hashlib.sha256).hexdigest()
    r=c.get('/api/appointments',params={'date':BASE['date']},headers={'Cookie':'atelier_staff='+token})
    assert r.status_code==200 and r.json()['appointments'][0]['id']==ident
    assert c.get('/api/appointments',headers={'Cookie':'atelier_staff='+token+'bad'}).status_code==401

def test_logout(clients):
    _,m,_=clients
    assert m.post('/api/staff/logout').status_code==200
    assert m.get('/api/staff/dashboard').status_code==401


def test_admin_manager_code(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'admin.sqlite'))
    monkeypatch.setenv('STAFF_PIN','admin')
    with TestClient(app,base_url='https://stevesbarbershopny.com') as client:
        assert client.post('/api/staff/login',json={'pin':'incorrect'}).status_code==401
        assert client.post('/api/staff/login',json={'pin':'admin'}).status_code==200
        assert client.get('/api/staff/dashboard').status_code==200


@pytest.mark.parametrize('day,opening,last_start,too_early,too_late',[
    ('2099-06-15','08:30','18:30','08:00','19:00'),
    ('2099-06-20','08:30','18:30','08:00','19:00'),
    ('2099-06-21','09:00','16:30','08:30','17:00'),
])
def test_weekday_and_sunday_hours(clients,day,opening,last_start,too_early,too_late):
    c,_,_=clients
    result=c.get('/api/availability',params={'date':day,'barber':'marco','service':'signature'})
    assert result.status_code==200
    available=result.json()['slots']
    assert available[0]==opening and available[-1]==last_start
    assert book(c,date=day,time=too_early).status_code==400
    assert book(c,date=day,time=too_late).status_code==400
    assert book(c,date=day,time=opening).status_code==201
    assert book(c,date=day,time=last_start).status_code==201


def test_price_board_catalog(clients):
    assert len(SERVICES)==12
    assert [s['price'] for s in SERVICES]==[25,40,31,25,15,15,22,6,30,20,45,65]
    c,_,_=clients
    for index,service in enumerate(SERVICES):
        result=book(c,serviceId=service['id'],date=f'2099-07-{index+10:02}')
        assert result.status_code==201
        with database() as db:
            row=db.execute('SELECT duration FROM appointments WHERE id=?',(result.json()['id'],)).fetchone()
            assert row['duration']==service['duration']


@pytest.mark.parametrize('ident,name',[('marco','David'),('james','Steve'),('andre','Joey'),('mike','Mike')])
def test_named_barber_access_and_booking(clients,monkeypatch,ident,name):
    c,_,_=clients
    monkeypatch.setenv('BARBER_PIN_'+name.upper(),'personal-test-code')
    result=book(c,barberId=ident)
    assert result.status_code==201
    with TestClient(app,base_url='https://stevesbarbershopny.com') as staff:
        assert staff.post('/api/staff/login',json={'barberId':ident,'pin':'personal-test-code'}).status_code==200
        rows=staff.get('/api/appointments',params={'date':BASE['date']}).json()['appointments']
        assert len(rows)==1 and rows[0]['barberId']==ident


@pytest.mark.parametrize('ident,name,code',[
    ('marco','David','stevedavid'),('james','Steve','stevesteve'),
    ('andre','Joey','stevejosey'),('mike','Mike','stevemike'),
])
def test_requested_codes_and_private_barber_panels(clients,monkeypatch,ident,name,code):
    public,_,_=clients
    monkeypatch.setenv('BARBER_PIN_'+name.upper(),code)
    own=book(public,barberId=ident).json()['id']
    other=book(public,barberId='mike' if ident!='mike' else 'marco').json()['id']
    with TestClient(app,base_url='https://stevesbarbershopny.com') as staff:
        assert staff.post('/api/staff/login',json={'barberId':ident,'pin':'wrong'}).status_code==401
        result=staff.post('/api/staff/login',json={'barberId':ident,'pin':code})
        assert result.status_code==200
        assert result.json()['session']=={'role':'barber','barberId':ident}
        rows=staff.get('/api/appointments',params={'date':BASE['date'],'barber':'all'}).json()['appointments']
        assert [row['id'] for row in rows]==[own]
        assert staff.get('/api/staff/dashboard').status_code==403
        assert staff.get('/api/staff/services').status_code==403
        assert staff.post('/api/staff/status',json={'id':other,'status':'completed'}).status_code==403
        assert staff.post('/api/staff/status',json={'id':own,'status':'completed'}).status_code==200
        assert staff.post('/api/staff/logout').status_code==200
        assert staff.get('/api/appointments').status_code==401


def test_requested_manager_code(clients,monkeypatch):
    public,_,_=clients
    monkeypatch.setenv('STAFF_PIN','steveadmin')
    with TestClient(app,base_url='https://stevesbarbershopny.com') as manager:
        assert manager.post('/api/staff/login',json={'pin':'admin'}).status_code==401
        result=manager.post('/api/staff/login',json={'pin':'steveadmin'})
        assert result.status_code==200 and result.json()['session']['role']=='manager'
        assert manager.get('/api/staff/dashboard').status_code==200
        assert len(manager.get('/api/staff/services').json()['team'])==4
