"""V1 adapter: deliberately usable ONLY with a freshly owned temporary database.

Not imported by the operational server. No CLI, public bind or database argument.
Loopback plaintext is an explicit integration-test transport, not Wi-Fi security.
"""
from collections import defaultdict, deque
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import ipaddress
import json
import logging
import math
from pathlib import Path
import secrets
import ssl
import tempfile
import threading
import time
from urllib.parse import urlparse, unquote
import uuid

from app.api.mobile_jobs import MobileJobsHandler
from app.database.database import ImageDatabase
from app.services.mobile_order_contract import MobileOrderContract, MobileOrderContractError
from app.services.order_operation_service import OrderOperationService, OrderOperationConflict, install_order_integrity

PREFIX = '/api/v1/mobile/order-sync/'


class ApiError(ValueError):
    def __init__(self, status, code):
        self.status, self.code = status, code


class OrderIntegrationEnvironment:
    def __init__(self, *, enable_writes=False):
        self._temporary = tempfile.TemporaryDirectory(prefix='doccione-order-sync-integration-')
        self._path = Path(self._temporary.name)/'integration.db'
        self.database = ImageDatabase(self._path)
        self.enable_writes = enable_writes is True
        self.limit = 120
        self._requests = defaultdict(deque)
        self._rate_lock = threading.Lock()
        self.fail_before_commit = None  # trusted local fault injection, never a request field
        self.drop_next_committed_response = False  # trusted loopback E2E fault, never remote
        with self.database.connection:
            self.database.connection.execute('CREATE TABLE order_sync_environment (id TEXT PRIMARY KEY)')
            self.database.connection.execute('INSERT INTO order_sync_environment VALUES(?)', (uuid.uuid4().hex,))
            self.database.connection.execute('''CREATE TABLE order_sync_rejections (
                id INTEGER PRIMARY KEY,code TEXT NOT NULL,device_id INTEGER,created_at TEXT NOT NULL)''')
            self.database.connection.execute('''CREATE TABLE order_sync_job_identity (
                actor TEXT NOT NULL, client_order_id TEXT NOT NULL, client_job_id TEXT NOT NULL,
                order_id INTEGER NOT NULL, order_job_id INTEGER NOT NULL,
                PRIMARY KEY(actor,client_order_id,client_job_id), UNIQUE(order_job_id))''')
            self.database.connection.execute('''CREATE TABLE order_sync_design_identity (
                actor TEXT NOT NULL,client_order_id TEXT NOT NULL,association_id TEXT NOT NULL,
                catalog_design_id TEXT NOT NULL,demand_line_id TEXT NOT NULL UNIQUE,order_id INTEGER NOT NULL,
                PRIMARY KEY(actor,client_order_id,association_id))''')
        install_order_integrity(self.database.connection)

    def assert_isolated(self):
        root = Path(self._temporary.name).resolve()
        actual = Path(self.database.connection.execute('PRAGMA database_list').fetchone()[2]).resolve()
        if (not root.is_dir() or root.parent != Path(tempfile.gettempdir()).resolve()
                or not root.name.startswith('doccione-order-sync-integration-')
                or actual != (root/'integration.db').resolve() or self.database.db_path.resolve() != actual):
            raise ApiError(503,'isolation_required')

    def close(self):
        self.database.close()
        self._temporary.cleanup()

    def allowed(self, actor, oid):
        device=self.database.connection.execute('SELECT active FROM mobile_devices WHERE id=?',(actor.split(':')[-1],)).fetchone()
        if not device or not device[0]:return False
        if oid is None:
            return True
        row=self.database.connection.execute('SELECT creator_device_id,is_archived FROM orders WHERE id=?',(oid,)).fetchone()
        return bool(row and str(row[0]) == actor.split(':')[-1] and not row[1])

    def catalog_handler(self):
        handler=object.__new__(MobileJobsHandler)
        handler.event_repo=self.database.event_repo
        return handler

    def resolve_design(self, opaque):
        # Enforce explicit public/reusable state even if legacy catalog is 'all'.
        found=self.catalog_handler()._catalog_design_by_id(opaque)
        if not found or not Path(found['path']).is_file():
            return None
        row=self.database.connection.execute('SELECT is_private,is_reusable FROM images WHERE path=?',(found['path'],)).fetchone()
        return found if row and not row[0] and row[1] else None

    def snapshot(self, oid):
        conn=self.database.connection
        order=conn.execute('SELECT client,whatsapp,observations,status FROM orders WHERE id=?',(oid,)).fetchone()
        jobs=[]
        for row in conn.execute('''SELECT j.*,i.client_job_id,p.code AS product_code,v.code AS variant_code
            FROM order_jobs j LEFT JOIN order_sync_job_identity i ON i.order_job_id=j.id
            LEFT JOIN products p ON p.id=j.product_id LEFT JOIN product_variants v ON v.id=j.variant_id
            WHERE j.order_id=? ORDER BY j.sort_order,j.id''',(oid,)):
            if not math.isfinite(float(row['subtotal'])) or float(row['subtotal'])<0:
                raise ApiError(422,'legacy_data_requires_desktop')
            designs=[{'demand_line_id':d[0],'quantity':d[1],'unit_kind':d[2],'association_id':d[3],'catalog_design_id':d[4]}
                for d in conn.execute('''SELECT d.design_line_id,d.quantity,d.unit_kind,i.association_id,i.catalog_design_id
                    FROM order_design_demand_lines d LEFT JOIN order_sync_design_identity i ON i.demand_line_id=d.design_line_id
                    WHERE d.order_job_id=?''',(row['id'],))]
            jobs.append({'desktop_job_id':str(row['id']),'client_job_id':row['client_job_id'],
                'product_code':row['product_code'],'variant_code':row['variant_code'] or '',
                'material':row['material'],'size':row['size'],'quantity':row['quantity'],
                'unit_kind':row['unit_kind'],'notes':row['notes'] or '',
                'subtotal':row['subtotal'],'status':row['status'],'designs':designs})
        identity=conn.execute('SELECT client_order_id FROM order_sync_job_identity WHERE order_id=? LIMIT 1',(oid,)).fetchone()
        return {'desktop_order_id':str(oid),'client_order_id':identity[0] if identity else None,'revision':OrderOperationService(self.database).revision(oid),
            'client':order[0],'whatsapp':order[1],'observations':order[2],'status':order[3],'jobs':jobs}

    def prepare(self, actor, data):
        db=self.database;conn=db.connection
        data=MobileOrderContract.check_catalog(conn,data,self.resolve_design)
        oid=int(data['desktop_order_id']) if data.get('desktop_order_id') else None
        if not self.allowed(actor,oid):
            raise ApiError(403,'forbidden')
        # An unresolved outcome must be replayed with the same client identity,
        # not converted into a second create with another operation ID.
        if oid is None and conn.execute('SELECT 1 FROM order_sync_job_identity WHERE actor=? AND client_order_id=?',
            (actor,data['client_order_id'])).fetchone():
            raise ApiError(409,'client_identity_exists')
        existing={j['id']:j for j in db.order_jobs(oid)} if oid else {}
        if oid and conn.execute('SELECT 1 FROM plancha_item_assignments WHERE order_id=? LIMIT 1',(oid,)).fetchone():
            raise ApiError(409,'production_committed')
        if oid:
            client_identity=conn.execute('SELECT DISTINCT client_order_id FROM order_sync_job_identity WHERE actor=? AND order_id=?',(actor,oid)).fetchall()
            if len(client_identity)!=1 or client_identity[0][0]!=data['client_order_id']:
                raise ApiError(409,'client_identity_mismatch')
            mapped={r[0] for r in conn.execute('SELECT client_job_id FROM order_sync_job_identity WHERE actor=? AND order_id=?',(actor,oid))}
            incoming_ids={j['client_job_id'] for j in data['jobs']}
            if not mapped <= incoming_ids or len(mapped)!=len(existing):
                raise ApiError(409,'job_removal_requires_desktop')
        jobs,designs,calculations=[],[],[]
        for position, incoming in enumerate(data['jobs']):
            identity=conn.execute('SELECT order_id,order_job_id FROM order_sync_job_identity WHERE actor=? AND client_order_id=? AND client_job_id=?',
                (actor,data['client_order_id'],incoming['client_job_id'])).fetchone()
            if identity and identity[0] != oid:
                raise ApiError(409,'client_identity_mismatch')
            previous=existing.get(identity[1]) if identity else None
            product=conn.execute('SELECT id,name FROM products WHERE code=?',(incoming['product_code'],)).fetchone()
            variant=conn.execute('SELECT id FROM product_variants WHERE code=? AND product_id=?',(incoming.get('variant_code',''),product[0])).fetchone()
            variant_id=variant[0] if variant else None
            signature=(product[0],variant_id,incoming.get('material',''),incoming.get('size',''),incoming['quantity'],incoming['unit_kind'])
            if previous:
                old=tuple(previous.get(k) for k in ('product_id','variant_id','material','size','quantity','unit_kind'))
                if old != signature:
                    # No safe historical repricing confirmation contract yet.
                    raise ApiError(409,'commercial_change_requires_desktop')
                job=dict(previous); calculation=None
            else:
                calculation=db.resolve_commercial_price(product_id=product[0],material=incoming.get('material',''),size=incoming.get('size',''),quantity=incoming['quantity'])
                rule=db.price_rule(calculation['rule_id']) if calculation.get('matched') else None
                if (not rule or rule.get('variant_id') != variant_id
                    or calculation.get('requires_confirmation') or calculation.get('calculation_type') not in ('fijo','unitario')):
                    raise ApiError(422,'commercial_validation_failed')
                if not math.isfinite(float(calculation['subtotal'])) or float(calculation['subtotal'])<0:
                    raise ApiError(422,'commercial_validation_failed')
                job={'title':product[1],'subtotal':calculation['subtotal'],'product_id':product[0],
                     'variant_id':variant_id,'status':'Recibido'}
            job.update(quantity=incoming['quantity'],unit_kind=incoming['unit_kind'],
                material=incoming.get('material',''),size=incoming.get('size',''),notes=incoming.get('notes',''),
                distribution_policy=previous.get('distribution_policy','partial') if previous else 'partial')
            jobs.append(job);calculations.append(calculation)
            for design in incoming['designs']:
                resolved=self.resolve_design(design['catalog_design_id'])
                if not resolved:
                    raise ApiError(422,'design_not_found')
                size=self.catalog_handler()._catalog_size_cm(incoming.get('size',''))
                if not math.isfinite(size) or size<=0:
                    raise ApiError(422,'design_size_unsupported')
                line=uuid.uuid5(uuid.NAMESPACE_URL,json.dumps([actor,data['client_order_id'],design['association_id']],ensure_ascii=False)).hex
                designs.append({'image_path':resolved['path'],'quantity':design['quantity'],'size_cm':size,
                    # Explicit key suppresses legacy path fallback when one image
                    # belongs to several works. None lets the new-job index resolve.
                    'order_job_id':previous['id'] if previous else None,
                    'order_job_index':position,'design_line_id':line,'unit_kind':incoming['unit_kind']})
        return data,oid,jobs,designs,calculations

    def write(self, actor, data, token):
        self.assert_isolated()
        if not self.enable_writes:
            raise ApiError(503,'writes_disabled')
        data=MobileOrderContract.validate(data)
        oid=int(data['desktop_order_id']) if data.get('desktop_order_id') else None
        def apply(db):
            validated,target,jobs,designs,calculations=self.prepare(actor,data)
            if target is None:
                target=db.create_order_with_details(data['client'],whatsapp=data.get('whatsapp',''),
                    observations=data.get('observations',''),jobs=jobs,designs=designs)
                db.connection.execute('UPDATE orders SET creator_device_id=? WHERE id=?',(int(actor.split(':')[-1]),target))
            else:
                values=dict(db.order(target));values.update(client=data['client'],whatsapp=data.get('whatsapp',''),observations=data.get('observations',''))
                db.save_order_snapshot(target,values,designs,jobs)
            persisted_jobs=db.order_jobs(target)
            if len(persisted_jobs)!=len(data['jobs']):raise ApiError(500,'persisted_mapping_invalid')
            for incoming,job,calculation in zip(data['jobs'],persisted_jobs,calculations):
                db.connection.execute('''INSERT INTO order_sync_job_identity VALUES(?,?,?,?,?)
                    ON CONFLICT(actor,client_order_id,client_job_id) DO NOTHING''',
                    (actor,data['client_order_id'],incoming['client_job_id'],target,job['id']))
                if calculation is not None:
                    db.save_order_job_price_snapshot(job['id'],calculation)
                for design in incoming['designs']:
                    line=uuid.uuid5(uuid.NAMESPACE_URL,json.dumps([actor,data['client_order_id'],design['association_id']],ensure_ascii=False)).hex
                    db.connection.execute('''INSERT INTO order_sync_design_identity VALUES(?,?,?,?,?,?)
                        ON CONFLICT(actor,client_order_id,association_id) DO UPDATE SET catalog_design_id=excluded.catalog_design_id''',
                        (actor,data['client_order_id'],design['association_id'],design['catalog_design_id'],line,target))
                    persisted=db.connection.execute('SELECT order_job_id,quantity,unit_kind FROM order_design_demand_lines WHERE design_line_id=? AND order_id=?',(line,target)).fetchone()
                    if not persisted or tuple(persisted)!=(job['id'],design['quantity'],incoming['unit_kind']):
                        raise ApiError(500,'persisted_mapping_invalid')
            if db.connection.execute('SELECT COUNT(*) FROM order_design_demand_lines WHERE order_id=?',(target,)).fetchone()[0]!=sum(len(j['designs']) for j in data['jobs']):
                raise ApiError(500,'persisted_mapping_invalid')
            return target
        def authorized(subject,target):
            device=self.database.event_repo.validate_session_token(token)
            return bool(device and subject==f"device:{device['id']}" and self.allowed(subject,target))
        return OrderOperationService(self.database).execute(actor=actor,operation_id=data['operation_id'],
            operation_type='order_snapshot_v1',payload=data,order_id=oid,expected_revision=data['expected_revision'],
            authorize=authorized,apply=apply,before_commit=self.fail_before_commit,
            result_data=lambda conn,target:{'contract_version':1,'desktop_order_id':str(target),'snapshot':self.snapshot(target)})


class OrderSyncHandler(MobileJobsHandler):
    def setup(self):
        self.request.settimeout(3)  # includes request-line/headers, before dispatch
        super().setup()

    def __init__(self,*args,environment,**kwargs):
        self.environment=environment
        super().__init__(*args,event_repo=environment.database.event_repo,event_bus=None,**kwargs)

    def _send_json_response(self,status_code,data):
        if status_code==200 and 'products' in data:
            # Additive V1 catalog metadata, no new endpoint or filesystem URL.
            designs=[]
            for row in self.environment.database.connection.execute(
                    'SELECT path,name,visible_width,visible_height FROM images WHERE is_reusable=1 AND is_private=0 ORDER BY name,path LIMIT 100'):
                opaque=self.environment.catalog_handler()._catalog_design_id(row['path'])
                if self.environment.resolve_design(opaque):
                    designs.append({'id':opaque,'name':row['name'],'preview_url':'',
                        'visible_width':row['visible_width'] or 0,'visible_height':row['visible_height'] or 0})
            data={**data,'designs':designs,'design_limit':100}
        json.dumps(data,allow_nan=False)  # do not emit invalid JSON for corrupt legacy catalog values
        server_id=self.environment.database.connection.execute('SELECT id FROM order_sync_environment').fetchone()[0]
        super()._send_json_response(status_code,{'contract_version':1,'integration_server_id':server_id,**data})

    def log_message(self,*args):
        pass  # never log Authorization/body/PII

    def finish(self):
        try:super().finish()
        finally:self.environment.database.close()

    def error(self,status,code):
        self.environment.database.connection.execute(
            "INSERT INTO order_sync_rejections(code,device_id,created_at) VALUES(?,?,datetime('now'))",(code,getattr(self,'device_id',None)))
        self.environment.database.connection.commit()
        self._send_json_response(status,{'contract_version':1,'persisted':False,'error':{'code':code}})

    def _send_error(self,status,message):
        self.error(status,'internal_error' if status>=500 else 'request_rejected')

    def read_body(self):
        raw=self.headers.get('Content-Length','')
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1 or not raw.isascii() or not raw.isdigit():
            raise ApiError(400,'invalid_framing')
        count=int(raw)
        if count<1 or count>MobileOrderContract.MAX_BYTES:
            raise ApiError(413,'payload_too_large')
        if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
            raise ApiError(415,'json_required')
        def pairs(items):
            result={}
            for key,value in items:
                if key in result: raise ValueError('duplicate key')
                result[key]=value
            return result
        try:
            body=self.rfile.read(count)
            if len(body)!=count:raise ValueError('truncated')
            value=json.loads(body.decode('utf-8'),object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
            if not isinstance(value,dict):raise ValueError('root')
            return value
        except TimeoutError:raise ApiError(408,'request_timeout')
        except (ValueError,UnicodeError,RecursionError):raise ApiError(400,'invalid_json')

    def dispatch(self, method):
        env=self.environment
        try:
            self.connection.settimeout(3)
            env.assert_isolated()
            path=urlparse(self.path).path
            now=time.monotonic()
            with env._rate_lock:
                hits=env._requests[self.client_address[0]]
                while hits and now-hits[0]>60:hits.popleft()
                if len(hits)>=env.limit:raise ApiError(429,'rate_limited')
                hits.append(now)
            if path==PREFIX+'pair' and method=='POST':
                data=self.read_body()
                if set(data)!={'code'} or not isinstance(data['code'],str) or len(data['code'])!=6:
                    raise ApiError(400,'pairing_invalid')
                ok,_,device,token=env.database.event_repo.register_device_with_pairing(data['code'],secrets.token_urlsafe(24),'integration','Integration only')
                if not ok:raise ApiError(401,'pairing_invalid')
                return self._send_json_response(201,{'contract_version':1,'device_id':device,'session_token':token})
            token=self._get_auth_token()
            device=env.database.event_repo.validate_session_token(token) if token else None
            if not device:raise ApiError(401,'unauthorized')
            self.device_id=device['id']
            actor=f"device:{device['id']}"
            if path==PREFIX+'capabilities' and method=='GET':
                return self._send_json_response(200,{'contract_version':1,'writes_enabled':env.enable_writes,
                    'integration_only':True,'device_id':device['id'],'limits':{'bytes':65536,'jobs':30,'designs_per_job':100,'order_list':100},
                    'features':{'validate':True,'create':env.enable_writes,'update':env.enable_writes,
                        'repricing_existing':False,'remove_jobs':False,'edit_committed_production':False}})
            if path==PREFIX+'catalog' and method=='GET':return self._list_catalog_products()
            if path==PREFIX+'orders' and method=='GET':
                rows=env.database.connection.execute('SELECT id FROM orders WHERE creator_device_id=? AND is_archived=0 ORDER BY id LIMIT 100',(device['id'],))
                return self._send_json_response(200,{'contract_version':1,'orders':[{'desktop_order_id':str(r[0]),'revision':OrderOperationService(env.database).revision(r[0])} for r in rows]})
            if path.startswith(PREFIX+'orders/') and method=='GET':
                value=path.removeprefix(PREFIX+'orders/')
                if not value.isascii() or not value.isdigit():raise ApiError(404,'not_found')
                oid=int(value)
                if not env.allowed(actor,oid):raise ApiError(403,'forbidden')
                with env.database.connection.order_transaction():snapshot=env.snapshot(oid)
                return self._send_json_response(200,{'contract_version':1,'snapshot':snapshot})
            if path.startswith(PREFIX+'operations/') and method=='GET':
                key=unquote(path.removeprefix(PREFIX+'operations/'))
                row=env.database.connection.execute('SELECT result_json FROM remote_order_operations WHERE actor=? AND operation_id=?',(actor,key)).fetchone()
                if not row:raise ApiError(404,'not_found')
                result=json.loads(row[0])
                if not env.allowed(actor,result['order_id']):raise ApiError(403,'forbidden')
                return self._send_json_response(200,result)
            if method=='POST' and path in (PREFIX+'validate',PREFIX+'operations'):
                if path.endswith('operations') and not env.enable_writes:raise ApiError(503,'writes_disabled')
                data=self.read_body()
                if data.get('contract_version')!=1 or type(data.get('contract_version')) is not int:raise ApiError(422,'version_unsupported')
                if path.endswith('validate'):
                    with env.database.connection.order_transaction():
                        validated,target,_,_,_=env.prepare(actor,data)
                        if target and OrderOperationService(env.database).revision(target)!=validated['expected_revision']:
                            raise ApiError(409,'revision_conflict')
                    return self._send_json_response(200,{'contract_version':1,'valid':True,'persisted':False})
                result=env.write(actor,data,token)
                if env.drop_next_committed_response:
                    env.drop_next_committed_response=False
                    self.close_connection=True
                    return  # real committed operation; client receives no HTTP response
                return self._send_json_response(200 if data.get('desktop_order_id') else 201,result)
            raise ApiError(404,'not_found')
        except MobileOrderContractError as error:self.error(error.status,error.code)
        except OrderOperationConflict as error:self.error(409,str(error))
        except ApiError as error:self.error(error.status,error.code)
        except PermissionError:self.error(403,'forbidden')
        except ValueError:self.error(409,'integrity_rejected')
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:
            logging.getLogger(__name__).exception('Isolated order adapter failed')
            self.error(500,'internal_error')

    def do_GET(self):self.dispatch('GET')
    def do_POST(self):self.dispatch('POST')
    def do_PATCH(self):self.error(405,'method_not_allowed')


@contextmanager
def integration_server(environment):
    environment.assert_isolated()
    # The caller cannot select a bind address or attach an operational database.
    server=ThreadingHTTPServer(('127.0.0.1',0),lambda *a,**k:OrderSyncHandler(*a,environment=environment,**k))
    server.daemon_threads=False  # server_close joins requests before the owned DB is removed
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown();server.server_close();thread.join()


@contextmanager
def secure_lan_integration_server(environment, *, bind_address, port,
                                  certificate, private_key,
                                  allowed_client_addresses):
    """Explicit TLS-only pilot listener for an already-isolated environment.

    This is intentionally separate from ``integration_server`` so automated
    tests retain loopback/ephemeral semantics.  All inputs are trusted local
    configuration: no HTTP request can enable this listener or its writes.
    """
    environment.assert_isolated()
    bind_ip = ipaddress.ip_address(bind_address)
    allowed = frozenset(str(ipaddress.ip_address(value))
                        for value in allowed_client_addresses)
    if (bind_ip.version != 4 or not bind_ip.is_private or bind_ip.is_loopback
            or not 1024 <= int(port) <= 65535 or not allowed):
        raise ValueError('private_lan_configuration_required')
    for value in allowed:
        candidate = ipaddress.ip_address(value)
        if candidate.version != 4 or not candidate.is_private or candidate.is_loopback:
            raise ValueError('private_lan_configuration_required')
    cert_path, key_path = Path(certificate).resolve(), Path(private_key).resolve()
    if not cert_path.is_file() or not key_path.is_file():
        raise ValueError('tls_material_required')

    class RestrictedOrderSyncHandler(OrderSyncHandler):
        def setup(self):
            if self.client_address[0] not in allowed:
                self.request.close()
                raise ConnectionAbortedError('client_not_allowed')
            super().setup()

    class QuietTlsServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            # TLS probes and clients going offline commonly reset before an
            # HTTP request. Do not leak tracebacks; real handler failures use
            # the sanitized application logger/JSON error path.
            error = __import__('sys').exc_info()[1]
            if isinstance(error, (ConnectionResetError, ConnectionAbortedError,
                                  BrokenPipeError, ssl.SSLError)):
                return
            super().handle_error(request, client_address)

    server = QuietTlsServer(
        (str(bind_ip), int(port)),
        lambda *a, **k: RestrictedOrderSyncHandler(
            *a, environment=environment, **k))
    server.daemon_threads = False
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'https://{bind_ip}:{server.server_port}'
    finally:
        server.shutdown();server.server_close();thread.join()


@contextmanager
def secure_usb_integration_server(environment, *, certificate, private_key,
                                  port=8875):
    """TLS-only Android USB pilot, reachable solely through ADB reverse.

    The fixed loopback binding and port are deliberate security boundaries.
    This entry point cannot expose the service to LAN and cannot attach an
    operational database; ``environment`` retains ownership of its temporary
    SQLite database and its explicit fictitious-write switch.
    """
    environment.assert_isolated()
    if int(port) != 8875:
        raise ValueError('usb_pilot_port_required')
    cert_path, key_path = Path(certificate).resolve(), Path(private_key).resolve()
    if not cert_path.is_file() or not key_path.is_file():
        raise ValueError('tls_material_required')

    class LoopbackOrderSyncHandler(OrderSyncHandler):
        def setup(self):
            if self.client_address[0] != '127.0.0.1':
                self.request.close()
                raise ConnectionAbortedError('usb_loopback_required')
            super().setup()

    class QuietTlsServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            error = __import__('sys').exc_info()[1]
            if isinstance(error, (ConnectionResetError, ConnectionAbortedError,
                                  BrokenPipeError, ssl.SSLError)):
                return
            super().handle_error(request, client_address)

    server = QuietTlsServer(
        ('127.0.0.1', 8875),
        lambda *a, **k: LoopbackOrderSyncHandler(
            *a, environment=environment, **k))
    server.daemon_threads = False
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'https://127.0.0.1:8875'
    finally:
        server.shutdown();server.server_close();thread.join()
