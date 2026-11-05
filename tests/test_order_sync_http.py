from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import http.client
import json
import sqlite3
import socket
import time
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image
import pytest

from app.api.order_sync_integration import OrderIntegrationEnvironment, integration_server, PREFIX


def request(url, route, token=None, payload=None, method=None, raw=None, headers=None):
    parsed=urlparse(url);conn=http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=10)
    values={'Content-Type':'application/json'}
    if token:values['Authorization']='Bearer '+token
    values.update(headers or {})
    body=raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
    conn.request(method or ('POST' if body is not None else 'GET'),PREFIX+route,body=body,headers=values)
    response=conn.getresponse();result=response.status,json.loads(response.read())
    conn.close();return result


@pytest.fixture
def env():
    value=OrderIntegrationEnvironment(enable_writes=True)
    db=value.database
    db.save_catalog_product(name='Producto fixture',price=100)
    product=db.connection.execute("SELECT code FROM products WHERE name='Producto fixture'").fetchone()[0]
    # Existing official price service filters by matching rule material.
    material=db.connection.execute('SELECT r.material FROM price_rules r JOIN products p ON p.id=r.product_id WHERE p.code=?',(product,)).fetchone()[0]
    image=value._path.parent/'fixture.png'
    Image.new('RGBA',(200,200),'red').save(image)
    db.connection.execute("INSERT INTO images(path,name,extension,size,modified,is_reusable,is_private,visible_width,visible_height) VALUES(?,'Fixture','.png',1,1,1,0,200,200)",(str(image),))
    db.connection.commit()
    opaque=value.catalog_handler()._catalog_design_id(str(image))
    value.payload={'contract_version':1,'operation_id':'op-1','client_order_id':'client-1',
        'desktop_order_id':None,'expected_revision':0,'client':'Cliente HTTP','whatsapp':'','observations':'',
        'jobs':[{'client_job_id':'job-1','product_code':product,'variant_code':'','material':material,'size':'5cm',
            'quantity':10,'unit_kind':'item','notes':'','designs':[{'association_id':'association-1','catalog_design_id':opaque,'quantity':4}]}]}
    yield value
    value.close()


def pair(env,url):
    code=env.database.event_repo.create_pairing_code()
    status,result=request(url,'pair',payload={'code':code})
    assert status==201,result
    return result['session_token'],result['device_id']


def test_http_create_replay_read_and_update(env):
    with integration_server(env) as url:
        token,_=pair(env,url)
        assert request(url,'capabilities',token)[1]['integration_only']
        assert request(url,'catalog',token)[0]==200
        validation_status,validation=request(url,'validate',token,env.payload)
        assert validation_status==200 and validation['contract_version']==1
        assert validation['valid'] is True and validation['persisted'] is False
        assert validation['integration_server_id']
        assert env.database.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
        status,result=request(url,'operations',token,env.payload)
        assert status==201,result
        assert result['persisted'] and result['snapshot']['revision']==result['revision']
        assert result['snapshot']['jobs'][0]['designs'][0]['association_id']=='association-1'
        assert request(url,'operations',token,env.payload)==(201,result)
        assert request(url,'operations/op-1',token)==(200,result)
        oid=result['desktop_order_id']
        assert request(url,'orders/'+oid,token)[1]['snapshot']==result['snapshot']
        data=deepcopy(env.payload);data.update(operation_id='edit',desktop_order_id=oid,expected_revision=result['revision'],observations='Cambio')
        data['jobs'].append({**deepcopy(data['jobs'][0]),'client_job_id':'job-2','designs':[]})
        status,updated=request(url,'operations',token,data)
        assert status==200,updated
        assert len(updated['snapshot']['jobs'])==2
        assert request(url,'operations',token,data)==(200,updated)
        assert request(url,'orders',token)[1]['orders'][0]['revision']==updated['revision']


def test_http_integration_realm_persists_across_listener_restart(env):
    with integration_server(env) as url:
        token,device=pair(env,url)
        first=request(url,'capabilities',token)[1]
        assert first['device_id']==device
    with integration_server(env) as url:
        second=request(url,'capabilities',token)[1]
        assert first['integration_server_id']==second['integration_server_id']
    another=OrderIntegrationEnvironment()
    try:
        with integration_server(another) as url:
            token,_=pair(another,url)
            assert request(url,'capabilities',token)[1]['integration_server_id']!=first['integration_server_id']
    finally:another.close()


def test_http_catalog_design_metadata_does_not_expose_paths_or_private_files(env):
    with integration_server(env) as url:
        token,_=pair(env,url)
        result=request(url,'catalog',token)[1]
        assert result['designs'][0]['id']==env.payload['jobs'][0]['designs'][0]['catalog_design_id']
        assert str(env._path.parent) not in json.dumps(result)
        env.database.connection.execute('UPDATE images SET is_private=1');env.database.connection.commit()
        assert request(url,'catalog',token)[1]['designs']==[]


def test_http_shared_image_work_identity_survives_edit_and_new_work(env):
    data=deepcopy(env.payload)
    second=deepcopy(data['jobs'][0]);second.update(client_job_id='sheets',quantity=2,unit_kind='sheet')
    second['designs'][0].update(association_id='second-association',quantity=1)
    data['jobs'].append(second)
    with integration_server(env) as url:
        token,_=pair(env,url)
        status,created=request(url,'operations',token,data);assert status==201,created
        data.update(operation_id='same-image-edit',desktop_order_id=created['desktop_order_id'],expected_revision=created['revision'])
        third=deepcopy(second);third.update(client_job_id='third-work')
        third['designs'][0]['association_id']='third-association';data['jobs'].append(third)
        status,updated=request(url,'operations',token,data);assert status==200,updated
        for incoming,persisted in zip(data['jobs'],updated['snapshot']['jobs']):
            assert persisted['client_job_id']==incoming['client_job_id']
            assert len(persisted['designs'])==1
            assert persisted['designs'][0]['association_id']==incoming['designs'][0]['association_id']
            assert persisted['designs'][0]['quantity']==incoming['designs'][0]['quantity']
            assert persisted['designs'][0]['unit_kind']==incoming['unit_kind']
        assert request(url,'operations',token,data)[1]==updated


def test_http_conflicts_access_revocation_and_no_admin_fields(env):
    with integration_server(env) as url:
        token,device=pair(env,url)
        assert request(url,'orders')[0]==401
        status,result=request(url,'operations',token,env.payload);assert status==201,result
        changed=deepcopy(env.payload);changed['observations']='different'
        assert request(url,'operations',token,changed)[1]['error']['code']=='operation_mismatch'
        changed.update(operation_id='new',desktop_order_id=result['desktop_order_id'],expected_revision=1)
        assert request(url,'operations',token,changed)[1]['error']['code']=='revision_conflict'
        other,_=pair(env,url)
        assert request(url,'orders/'+result['desktop_order_id'],other)[0]==403
        assert request(url,'operations/op-1',other)[0]==404
        invalid=deepcopy(env.payload);invalid['paid_amount']=100
        assert request(url,'validate',token,invalid)[0]==422
        env.database.event_repo.deactivate_device(device)
        assert request(url,'operations/op-1',token)[0]==401


def test_http_limits_bad_json_version_and_rate(env):
    with integration_server(env) as url:
        token,_=pair(env,url)
        for raw in (b'[]',b'{"x":1,"x":2}',b'\xff',b'{"value":NaN}'):
            assert request(url,'validate',token,raw=raw)[0]==400
        assert request(url,'validate',token,raw=b'x'*65537)[0]==413
        assert request(url,'validate',token,{**env.payload,'contract_version':2})[1]['error']['code']=='version_unsupported'
        env.limit=1
        assert request(url,'capabilities',token)[0]==429
        assert env.database.connection.execute('SELECT COUNT(*) FROM order_sync_rejections').fetchone()[0]>=7


def test_http_failure_response_lost_and_restart(env):
    with integration_server(env) as url:
        token,_=pair(env,url)
        def fail(_):raise RuntimeError('secret internal path')
        env.fail_before_commit=fail
        status,error=request(url,'operations',token,env.payload)
        assert status==500 and 'secret' not in str(error)
        for table in ['orders','order_jobs','remote_order_operations','order_sync_job_identity','app_events']:
            assert env.database.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0
        env.fail_before_commit=None
        result=request(url,'operations',token,env.payload)[1]  # discard response to model lost acknowledgement
    with integration_server(env) as restarted:
        assert request(restarted,'operations',token,env.payload)[1]==result
        assert request(restarted,'operations/op-1',token)[1]==result


def test_http_concurrent_retries(env):
    with integration_server(env) as url:
        token,_=pair(env,url)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:request(url,'operations',token,env.payload),range(2)))
        assert results[0]==results[1],results
        assert env.database.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1


def test_default_disabled_cannot_be_enabled_by_payload():
    value=OrderIntegrationEnvironment()
    try:
        with integration_server(value) as url:
            token,_=pair(value,url)
            assert request(url,'operations',token,{'enable_writes':True,'test_mode':True})[1]['error']['code']=='writes_disabled'
            assert not request(url,'capabilities',token)[1]['writes_enabled']
    finally:value.close()


@pytest.mark.parametrize('change,code',[('product','product_invalid'),('variant','variant_invalid'),
    ('design','design_not_found'),('private','design_not_found'),('quantity','validation_failed')])
def test_http_invalid_catalog_and_quantity_never_create(env,change,code):
    data=deepcopy(env.payload);job=data['jobs'][0]
    if change=='product':job['product_code']='does-not-exist'
    elif change=='variant':job['variant_code']='does-not-exist'
    elif change=='design':job['designs'][0]['catalog_design_id']='0'*24
    elif change=='private':
        env.database.connection.execute('UPDATE images SET is_private=1');env.database.connection.commit()
    else:job['designs'][0]['quantity']=11
    with integration_server(env) as url:
        token,_=pair(env,url)
        status,result=request(url,'operations',token,data)
        assert status==422,result
        assert result['error']['code']==code
        assert env.database.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0


def test_http_active_variant_and_historical_price(env):
    db=env.database
    product=db.connection.execute('SELECT id FROM products WHERE code=?',(env.payload['jobs'][0]['product_code'],)).fetchone()[0]
    db.connection.execute("INSERT INTO product_variants(product_id,code,name,material,size,created_at,updated_at) VALUES(?,'fixture-variant','Variante real',?,'5cm','now','now')",(product,env.payload['jobs'][0]['material']))
    variant=db.connection.execute("SELECT id FROM product_variants WHERE code='fixture-variant'").fetchone()[0]
    db.connection.execute('UPDATE price_rules SET variant_id=?,size=? WHERE product_id=?',(variant,'5cm',product));db.connection.commit()
    env.payload['jobs'][0]['variant_code']='fixture-variant'
    with integration_server(env) as url:
        token,_=pair(env,url)
        status,created=request(url,'operations',token,env.payload);assert status==201,created
        oid=int(created['desktop_order_id']);old_price=db.order_jobs(oid)[0]['subtotal']
        db.register_order_payment(oid,10,'Efectivo',idempotency_key='fixture-payment')
        db.connection.execute('UPDATE price_rules SET price=9999 WHERE product_id=?',(product,));db.connection.commit()
        from app.services.order_operation_service import OrderOperationService
        data=deepcopy(env.payload);data.update(operation_id='notes',desktop_order_id=str(oid),expected_revision=OrderOperationService(db).revision(oid),observations='Sin recotizar')
        assert request(url,'operations',token,data)[0]==200
        assert db.order_jobs(oid)[0]['subtotal']==old_price
        assert len(db.order_payments(oid))==1
        data.update(operation_id='price-change',expected_revision=OrderOperationService(db).revision(oid))
        data['jobs'][0]['quantity']=11
        assert request(url,'operations',token,data)[1]['error']['code']=='commercial_change_requires_desktop'


def test_http_competing_updates_and_client_identity(env):
    with integration_server(env) as url:
        token,_=pair(env,url)
        created=request(url,'operations',token,env.payload)[1]
        data=deepcopy(env.payload);data.update(desktop_order_id=created['desktop_order_id'],expected_revision=created['revision'])
        def update(key):return request(url,'operations',token,{**data,'operation_id':key,'observations':key})
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(update,['a','b']))
        assert sorted(r[0] for r in results)==[200,409],results
        latest=next(r[1] for r in results if r[0]==200)
        data.update(operation_id='bad-identity',client_order_id='other',expected_revision=latest['revision'])
        assert request(url,'operations',token,data)[1]['error']['code']=='client_identity_mismatch'


def test_http_pairing_code_one_use_and_framing(env):
    with integration_server(env) as url:
        code=env.database.event_repo.create_pairing_code()
        first=request(url,'pair',payload={'code':code});assert first[0]==201
        assert request(url,'pair',payload={'code':code})[0]==401
        token=first[1]['session_token']
        assert request(url,'validate',token,raw=b'{}',headers={'Content-Length':'-1'})[0]==400
        assert request(url,'validate',token,raw=b'{}',headers={'Content-Type':'text/plain'})[0]==415


def test_http_backup_restore_and_integrity(env):
    from app.database.database import ImageDatabase
    from app.services.order_operation_service import install_order_integrity
    with integration_server(env) as url:
        token,_=pair(env,url)
        original=request(url,'operations',token,env.payload)[1]
    restored=OrderIntegrationEnvironment(enable_writes=True)
    try:
        restored.database.close()
        with closing(sqlite3.connect(restored._path)) as target:env.database.connection.backup(target)
        restored.database=ImageDatabase(restored._path)
        install_order_integrity(restored.database.connection)
        install_order_integrity(restored.database.connection)
        assert restored.database.connection.execute('PRAGMA foreign_key_check').fetchall()==[]
        with integration_server(restored) as url:
            assert request(url,'operations/op-1',token)[1]==original
            assert request(url,'operations',token,env.payload)[1]==original
    finally:restored.close()


def test_operational_handler_namespace_stays_disabled(env):
    import threading
    from http.server import ThreadingHTTPServer
    from app.api.mobile_jobs import MobileJobsHandler
    class DefaultHandler(MobileJobsHandler):
        def finish(self):
            try:super().finish()
            finally:env.database.close()
    server=ThreadingHTTPServer(('127.0.0.1',0),lambda *a,**k:DefaultHandler(*a,event_repo=env.database.event_repo,event_bus=None,**k))
    server.daemon_threads=False
    worker=threading.Thread(target=server.serve_forever);worker.start()
    try:
        status,result=request(f'http://127.0.0.1:{server.server_port}','operations?test_mode=true',payload={**env.payload,'enable_writes':True})
        assert status==503 and result['error']['code']=='order_sync_disabled'
        assert env.database.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
    finally:server.shutdown();server.server_close();worker.join()


def test_http_real_response_loss_and_recovery(env):
    with integration_server(env) as url:
        token,_=pair(env,url)
        parsed=urlparse(url);conn=http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=10)
        conn.request('POST',PREFIX+'operations',body=json.dumps(env.payload),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        conn.close()  # close without reading any acknowledgement
        for _ in range(30):
            status,confirmed=request(url,'operations/op-1',token)
            if status==200:break
            time.sleep(.03)
        assert status==200,confirmed
        assert request(url,'operations',token,env.payload)[1]==confirmed
        assert env.database.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1


def test_http_production_commitment_is_blocked(env):
    from app.services.order_production_service import OrderProductionService
    from app.services.production_batch_service import ProductionBatchService
    from app.services.order_operation_service import OrderOperationService
    with integration_server(env) as url:
        token,_=pair(env,url)
        status,created=request(url,'operations',token,env.payload);assert status==201,created
        oid=int(created['desktop_order_id']);jid=env.database.order_jobs(oid)[0]['id']
        production=OrderProductionService(env.database)
        ProductionBatchService(env.database).save(production.preview(oid,{jid:1}))
        before=production.snapshot(oid)
        data=deepcopy(env.payload);data.update(operation_id='blocked',desktop_order_id=str(oid),expected_revision=OrderOperationService(env.database).revision(oid),observations='no')
        status,result=request(url,'operations',token,data)
        assert status==409 and result['error']['code']=='production_committed'
        assert production.snapshot(oid)==before


@pytest.mark.parametrize('table',['order_jobs','order_design_demand_lines','order_events','remote_order_operations'])
def test_http_injected_sql_failure_rolls_back_all(env,table):
    env.database.connection.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected SQL secret'); END")
    env.database.connection.commit()
    with integration_server(env) as url:
        token,_=pair(env,url)
        status,result=request(url,'operations',token,env.payload)
        assert status==500 and 'secret' not in str(result)
        for name in ['orders','order_jobs','order_design_demand_lines','remote_order_operations','order_sync_job_identity','order_sync_design_identity','app_events']:
            assert env.database.connection.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]==0,name


def test_shared_flutter_fixture_through_http(env):
    root=Path(__file__).resolve().parents[1]
    data=json.loads((root/'tests/fixtures/order_sync_v1_request.json').read_text(encoding='utf-8'))
    env.database.connection.execute('UPDATE products SET code=? WHERE code=?',('fixture-code',env.payload['jobs'][0]['product_code']))
    env.database.connection.commit()
    with integration_server(env) as url:
        token,_=pair(env,url)
        status,response=request(url,'operations',token,data)
        assert status==201,response
        assert [j['unit_kind'] for j in response['snapshot']['jobs']]==['item','sheet']
        # Actual HTTP receipt, no token/credentials/paths. Consumed by Dart test.
        (root/'artifacts/s2a2-http-contract-response.json').write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')


@pytest.mark.parametrize('invalid',['size','negative_price','infinite_price'])
def test_http_nonfinite_geometry_and_invalid_official_price(env,invalid):
    data=deepcopy(env.payload)
    if invalid=='size':data['jobs'][0]['size']='inf'
    else:
        product=data['jobs'][0]['product_code']
        price=-1 if invalid=='negative_price' else float('inf')
        env.database.connection.execute('UPDATE price_rules SET price=? WHERE product_id=(SELECT id FROM products WHERE code=?)',(price,product))
        env.database.connection.commit()
    with integration_server(env) as url:
        token,_=pair(env,url)
        status,result=request(url,'operations',token,data)
        assert status==422,result
        assert env.database.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0


def test_http_incomplete_headers_timeout_without_writes(env):
    with integration_server(env) as url:
        parsed=urlparse(url)
        with socket.create_connection((parsed.hostname,parsed.port),timeout=6) as connection:
            connection.sendall(b'POST /api/v1/mobile/order-sync/operations HTTP/1.1\r\nHost: local\r\n')
            assert connection.recv(1024)==b''
        assert env.database.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0


def test_http_published_design_with_missing_file_is_rejected(env):
    (env._path.parent/'fixture.png').unlink()  # only this fixture's generated image
    with integration_server(env) as url:
        token,_=pair(env,url)
        status,result=request(url,'operations',token,env.payload)
        assert status==422 and result['error']['code']=='design_not_found'
        assert env.database.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
