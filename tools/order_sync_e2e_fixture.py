"""Trusted stdio fixture for Flutter tests. No operational DB or public listener.

Commands are from the local test process, NOT HTTP endpoints. All data is fake.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app.api.order_sync_integration import OrderIntegrationEnvironment, integration_server


def emit(value):
    print('S2B:'+json.dumps(value), flush=True)


def main():
    env=OrderIntegrationEnvironment(enable_writes=True)
    stack=ExitStack()
    try:
        db=env.database
        db.save_catalog_product(name='Producto integración Flutter',price=100)
        product=db.connection.execute("SELECT code FROM products WHERE name='Producto integración Flutter'").fetchone()[0]
        material=db.connection.execute('SELECT r.material FROM price_rules r JOIN products p ON p.id=r.product_id WHERE p.code=?',(product,)).fetchone()[0]
        pid=db.connection.execute('SELECT id FROM products WHERE code=?',(product,)).fetchone()[0]
        db.connection.execute("INSERT INTO product_variants(product_id,code,name,material,size,created_at,updated_at) VALUES(?,'integration-variant','FICTICIA',?,'5cm','now','now')",(pid,material))
        variant=db.connection.execute("SELECT id FROM product_variants WHERE code='integration-variant'").fetchone()[0]
        db.connection.execute("UPDATE price_rules SET variant_id=?,size='5cm' WHERE product_id=?",(variant,pid))
        designs=[]
        for i in range(3):
            image=env._path.parent/f'ficticio-{i}.png'
            Image.new('RGB',(200,200),(40*i,50,90)).save(image)
            db.connection.execute("INSERT INTO images(path,name,extension,size,modified,is_reusable,is_private,visible_width,visible_height) VALUES(?,? ,'.png',1,1,1,0,200,200)",(str(image),f'FICTICIO {i}'))
            designs.append(env.catalog_handler()._catalog_design_id(str(image)))
        db.connection.commit()
        url=stack.enter_context(integration_server(env))
        emit({'url':url,'code':db.event_repo.create_pairing_code(),'product':product,'variant':'integration-variant','material':material,'designs':designs})
        for line in sys.stdin:
            command=json.loads(line);action=command['action']
            if action=='close':break
            if action=='desktop_edit':
                # Trusted Desktop SQL path proves shared triggers observe non-HTTP writes.
                db.connection.execute('UPDATE orders SET observations=? WHERE id=?',(command['notes'],command['id']))
                db.connection.commit();emit({'ok':True})
            elif action=='stats':
                emit({'orders':db.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0],
                    'jobs':db.connection.execute('SELECT COUNT(*) FROM order_jobs').fetchone()[0],
                    'receipts':db.connection.execute('SELECT COUNT(*) FROM remote_order_operations').fetchone()[0],
                    'snapshot':env.snapshot(int(command['id'])) if command.get('id') else None})
            elif action=='drop_response':
                env.drop_next_committed_response=True;emit({'ok':True})
            elif action=='fail_before_commit':
                def fail(_):
                    env.fail_before_commit=None
                    raise RuntimeError('E2E deliberately interrupted before commit')
                env.fail_before_commit=fail;emit({'ok':True})
            elif action=='timeout':
                def delay(_):
                    env.fail_before_commit=None
                    time.sleep(.5)
                env.fail_before_commit=delay;emit({'ok':True})
            elif action=='offline':
                stack.close();emit({'ok':True})
            elif action=='restart':
                stack.close();stack=ExitStack()
                url=stack.enter_context(integration_server(env));emit({'url':url})
            elif action=='pair':emit({'code':db.event_repo.create_pairing_code()})
            elif action=='revoke':
                db.event_repo.deactivate_device(int(command['device_id']));emit({'ok':True})
            elif action=='expire':
                db.connection.execute("UPDATE mobile_devices SET session_expires_at='2000-01-01' WHERE id=?",(command['device_id'],))
                db.connection.commit();emit({'ok':True})
            elif action=='production':
                from app.services.order_production_service import OrderProductionService
                from app.services.production_batch_service import ProductionBatchService
                oid=int(command['id']);jid=db.order_jobs(oid)[0]['id']
                ProductionBatchService(db).save(OrderProductionService(db).preview(oid,{jid:1}))
                emit({'ok':True})
            elif action=='change_price':
                db.connection.execute('UPDATE price_rules SET price=price*3 WHERE product_id=?',(pid,))
                db.connection.commit();emit({'ok':True})
            else:raise ValueError('Unknown trusted fixture action')
    finally:
        stack.close();env.close()


if __name__=='__main__':main()
