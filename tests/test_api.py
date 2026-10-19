from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import sqlite3
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app, database, migrate, SERVICES, save_credential, key_for

BASE={'barberId':'marco','serviceId':'signature','date':'2099-06-15','time':'10:00','name':'Cliente Demo','email':'demo@example.com','phone':'2025550101'}
@pytest.fixture
def clients(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'test.sqlite'))
    monkeypatch.setenv('STAFF_PIN','manager-test-code')
    monkeypatch.setenv('BARBER_PIN_MARCO','marco-test-code')
    with TestClient(app,base_url='https://stevesbarbershopny.com') as public:
        with database(True) as db:
            save_credential(db,'manager','all','manager-test-code')
            save_credential(db,'barber','marco','marco-test-code')
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

def test_database_session_signature_and_migration(clients):
    c,_,_=clients
    ident=book(c).json()['id']
    migrate()
    payload=f'manager.all.{int(time.time()*1000)+60000}'
    with database() as db: key=key_for(db,'manager','all')
    token=payload+'.'+hmac.new(key.encode(),payload.encode(),hashlib.sha256).hexdigest()
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
        with database(True) as db: save_credential(db,'manager','all','admin')
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
    with database(True) as db: save_credential(db,'barber',ident,'personal-test-code')
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
    with database(True) as db: save_credential(db,'barber',ident,code)
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
    with database(True) as db: save_credential(db,'manager','all','steveadmin')
    with TestClient(app,base_url='https://stevesbarbershopny.com') as manager:
        assert manager.post('/api/staff/login',json={'pin':'admin'}).status_code==401
        result=manager.post('/api/staff/login',json={'pin':'steveadmin'})
        assert result.status_code==200 and result.json()['session']['role']=='manager'
        assert manager.get('/api/staff/dashboard').status_code==200
        assert len(manager.get('/api/staff/services').json()['team'])==4


@pytest.mark.parametrize('day,hour,minute,first_slot',[
    (15,8,0,'08:30'),(15,8,20,'08:30'),(15,8,40,'09:00'),
    (21,8,45,'09:00'),(21,9,10,'09:30'),
])
def test_same_day_availability_starts_at_opening_without_advance_buffer(clients,monkeypatch,day,hour,minute,first_slot):
    import app.main as main
    from datetime import datetime
    class FixedDateTime(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2099,6,day,hour,minute,tzinfo=main.NY)
    monkeypatch.setattr(main,'datetime',FixedDateTime)
    public,_,_=clients
    selected=f'2099-06-{day:02}'
    result=public.get('/api/availability',params={'date':selected,'barber':'marco','service':'signature'})
    assert result.status_code==200
    assert result.json()['slots'][0]==first_slot
    assert book(public,date=selected,time=first_slot).status_code==201
    if hour*60+minute>=main.opening_hours(selected)[0]:
        assert book(public,date=selected,time='09:00' if day==21 else '08:30').status_code==409


@pytest.mark.parametrize('day,opening,closing',[
    ('2099-06-15','08:30',19*60),
    ('2099-06-20','08:30',19*60),
    ('2099-06-21','09:00',17*60),
])
@pytest.mark.parametrize('service',SERVICES,ids=lambda s:s['id'])
def test_each_service_last_half_hour_slot_respects_closing(clients,day,opening,closing,service):
    public,_,_=clients
    opening_minutes=int(opening[:2])*60+int(opening[3:])
    start=opening_minutes+((closing-service['duration']-opening_minutes)//30)*30
    expected=f'{start//60:02}:{start%60:02}'
    result=public.get('/api/availability',params={'date':day,'barber':'marco','service':service['id']})
    assert result.status_code==200
    available=result.json()['slots']
    assert available[0]==opening and available[-1]==expected
    assert all(int(t[:2])*60+int(t[3:])+service['duration']<=closing for t in available)
    assert book(public,date=day,time=expected,serviceId=service['id']).status_code==201
    assert all((int(t[:2])*60+int(t[3:])-opening_minutes)%30==0 for t in available)
    late=start+30
    assert book(public,date=day,time=f'{late//60:02}:{late%60:02}',serviceId=service['id']).status_code==400


def test_half_hour_opening_slots_respect_real_occupied_duration(clients):
    public,manager,_=clients
    first=book(public,time='08:30',serviceId='beard')
    assert first.status_code==201
    result=slots(public,service='beard').json()['slots']
    assert '08:30' not in result and '08:45' not in result and '09:00' in result
    assert book(public,time='08:45',serviceId='beard').status_code==400
    assert book(public,time='09:00',serviceId='beard').status_code==201
    assert manager.post('/api/staff/status',json={'id':first.json()['id'],'status':'cancelled'}).status_code==200
    assert '08:30' in slots(public,service='beard').json()['slots']


def test_requested_defaults_persist_without_environment(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'defaults.sqlite'))
    monkeypatch.setenv('STAFF_PIN','obsolete-env-code')
    with TestClient(app,base_url='https://stevesbarbershopny.com') as client:
        for ident,pin in [('all','steveadmin'),('marco','stevedavid'),('james','stevesteve'),('andre','stevejosey'),('mike','stevemike')]:
            payload={'pin':pin,**({'barberId':ident} if ident!='all' else {})}
            assert client.post('/api/staff/login',json=payload).status_code==200
        with database() as db:
            rows=db.execute('SELECT * FROM staff_credentials').fetchall()
            assert len(rows)==5
            assert all(len(row['pin_hash'])==64 for row in rows)
            assert 'stevedavid' not in str([dict(row) for row in rows])

@pytest.mark.parametrize('ident',['marco','james','andre','mike','new'])
def test_manager_changes_password_persist_and_revoke_sessions(clients,monkeypatch,ident):
    public,manager,_=clients
    old={'marco':'marco-test-code','james':'stevesteve','andre':'stevejosey','mike':'stevemike','new':'new-barber-code'}[ident]
    if ident=='new':
        ident=manager.post('/api/staff/team',json={'name':'New barber','serviceIds':['beard'],'accessCode':old}).json()['id']
    with TestClient(app,base_url='https://stevesbarbershopny.com') as staff:
        assert staff.post('/api/staff/login',json={'barberId':ident,'pin':old}).status_code==200
        change={'staffId':ident,'accessCode':'replacement-code'}
        assert public.post('/api/staff/password',json=change).status_code==401
        assert staff.post('/api/staff/password',json=change).status_code==403
        assert manager.post('/api/staff/password',json=change).status_code==200
        assert staff.get('/api/appointments').status_code==401
        monkeypatch.setenv('BARBER_PIN_DAVID',old)
        migrate()
        assert staff.post('/api/staff/login',json={'barberId':ident,'pin':old}).status_code==401
        assert staff.post('/api/staff/login',json={'barberId':ident,'pin':'replacement-code'}).status_code==200
        assert staff.get('/api/appointments').status_code==200
        assert 'replacement-code' not in public.get('/api/team').text
    for value in ['short',' '*8]:
        assert manager.post('/api/staff/password',json={'staffId':ident,'accessCode':value}).status_code==400
    assert manager.post('/api/staff/password',json={'staffId':'missing','accessCode':'valid-new-code'}).status_code==400


def test_customers_saved_once_and_shown_with_latest_contact(clients):
    public,manager,_=clients
    first=book(public,email=' CLIENT@Example.com ').json()['id']
    second=book(public,time='11:00',email='client@example.com',name='Updated Client',phone='2025550199').json()['id']
    with database() as db:
        customer=db.execute('SELECT * FROM customers').fetchone()
        assert db.execute('SELECT count(*) FROM customers').fetchone()[0]==1
        assert customer['email']=='client@example.com'
        assert customer['name']=='Updated Client' and customer['phone']=='2025550199'
        assert all(row['customer_id']==customer['id'] for row in db.execute('SELECT customer_id FROM appointments'))
    manager.post('/api/staff/status',json={'id':first,'status':'completed'})
    result=manager.get('/api/staff/dashboard').json()['clients']
    assert len(result)==1 and result[0]['name']=='Updated Client'
    assert result[0]['visits'][0]['id']==first and result[0]['upcoming'][0]['id']==second
    assert book(public,time='11:00',email='rejected@example.com').status_code==409
    with database() as db: assert db.execute('SELECT count(*) FROM customers').fetchone()[0]==1
    migrate()
    with database() as db: assert db.execute('SELECT id FROM customers').fetchone()['id']==customer['id']


def test_existing_appointments_backfill_customer_records(clients):
    public,manager,_=clients
    first=book(public).json()['id']
    with database(True) as db:
        db.execute('DROP INDEX appointments_customer_id')
        db.execute('ALTER TABLE appointments DROP COLUMN customer_id')
        db.execute('DROP TABLE customers')
        db.execute("DELETE FROM node_migrations WHERE name='0006_customers.sql'")
    migrate()
    with database() as db:
        customer=db.execute('SELECT * FROM customers').fetchone()
        appointment=db.execute('SELECT customer_id FROM appointments WHERE id=?',(first,)).fetchone()
        assert customer['email']==BASE['email'] and customer['id']==appointment['customer_id']
    assert manager.get('/api/staff/dashboard').json()['clients'][0]['upcoming'][0]['id']==first


def test_availability_marks_reserved_starts_without_customer_details(clients):
    public,manager,_=clients
    ident=book(public,time='10:00',serviceId='complete').json()['id']
    result=slots(public).json()
    assert '10:00' not in result['slots'] and '10:30' not in result['slots']
    assert {'time':'10:00','reason':'reserved'} in result['unavailable']
    assert {'time':'10:30','reason':'reserved'} in result['unavailable']
    assert '11:00' in result['slots']
    assert BASE['email'] not in json.dumps(result)
    manager.post('/api/staff/status',json={'id':ident,'status':'cancelled'})
    result=slots(public).json()
    assert '10:00' in result['slots'] and '10:30' in result['slots']
    assert not result['unavailable']


def test_shared_busyness_editable_by_manager_and_barber_and_persists(clients):
    public,manager,barber=clients
    assert public.get('/api/busyness').json()=={'percentage':None,'level':None,'updatedAt':None}
    assert public.post('/api/staff/busyness',json={'percentage':75}).status_code==401
    for client,percentage,level in [(manager,0,'low'),(barber,33,'low'),(manager,34,'moderate'),(barber,66,'moderate'),(manager,67,'busy'),(barber,100,'busy')]:
        result=client.post('/api/staff/busyness',json={'percentage':percentage})
        assert result.status_code==200 and result.json()['level']==level
        visible=public.get('/api/busyness').json()
        assert visible['percentage']==percentage and visible['updatedAt']
        assert 'updated_by_subject' not in str(visible)
    migrate()
    assert public.get('/api/busyness').json()['percentage']==100
    with database() as db:
        row=db.execute('SELECT * FROM shop_busyness').fetchone()
        assert row['updated_by_role']=='barber' and row['updated_by_subject']=='marco'

@pytest.mark.parametrize('percentage',[-1,101,50.5,'50',True,None])
def test_invalid_busyness_does_not_change_persisted_value(clients,percentage):
    public,manager,_=clients
    manager.post('/api/staff/busyness',json={'percentage':50})
    assert manager.post('/api/staff/busyness',json={'percentage':percentage}).status_code==400
    assert public.get('/api/busyness').json()['percentage']==50
