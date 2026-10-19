from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import sqlite3
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app, database, migrate

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
    assert len(team)==3
    assert team[0]['serviceIds']==['signature','beard','complete']
    assert team[0]['role']=='Master Barber'
    assert 'pin' not in json.dumps(team).lower()

def test_booking_and_overlap(clients):
    c,m,_=clients
    assert '10:00' in slots(c).json()['slots']
    r=book(c);assert r.status_code==201
    assert book(c).status_code==409
    assert book(c,time='10:30').status_code==409
    assert book(c,time='11:00').status_code==201
    assert book(c,barberId='james').status_code==201
    assert '10:00' not in slots(c).json()['slots']
    rows=m.get('/api/appointments',params={'date':BASE['date']}).json()['appointments']
    assert len(rows)==3 and rows[0]['customerName']==BASE['name']
    with database() as db:assert db.execute('SELECT count(*) FROM occupied_slots WHERE appointment_id=?',(r.json()['id'],)).fetchone()[0]==4
@pytest.mark.parametrize('changes',[{'email':'invalid'},{'name':''},{'name':' '},{'phone':'123'},{'phone':'       '},{'date':'2000-01-01'},{'date':'2099-02-31'},{'date':'not-date'},{'barberId':'missing'},{'serviceId':'missing'},{'time':'19:00'},{'time':'18:00'},{'notes':'x'*501}])
def test_invalid_booking(clients,changes):assert book(clients[0],**changes).status_code==400

def test_duration_and_concurrency(clients):
    c,_,_=clients
    assert book(c,time='13:00',serviceId='complete').status_code==201
    assert book(c,time='14:00',serviceId='beard').status_code==409
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
    assert len(result.json()['team'])==4
    assert m.post('/api/staff/team',json={**person,'name':' BARBERO  NUEVO '}).status_code==409
    assert m.post('/api/staff/team',json={**person,'name':'Marco Reyes'}).status_code==409
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
