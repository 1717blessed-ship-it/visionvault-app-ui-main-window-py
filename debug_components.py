from pathlib import Path
import tempfile
from app.database.database import ImageDatabase
from costos.models.cost_component import CostComponent

with tempfile.TemporaryDirectory() as d:
    db = ImageDatabase(Path(d) / 'x.db')
    model_id = db.save_cost_rule(name='Modelo', components=[CostComponent(name='Embalaje', code='packaging', value_type='fixed', value=12.0)])
    model = db.cost_model(model_id)
    print('model row', model)
    print('components_json', model.get('components_json'))
    rule = db._build_cost_rule_from_model(model)
    print('built components', [(c.name, c.code, c.value_type, c.value, c.enabled, c.order) for c in rule.components])
    price_rule_id = db.save_price_rule(material='Vinilo Premium', size='15cm', min_quantity=2, price=120.0, cost_model_id=model_id)
    price_rule = db.price_rule(price_rule_id)
    print('price_rule row', price_rule)
    resolved, warning = db.resolve_price_rule_cost_model(price_rule)
    print('resolved', resolved, warning)
    if resolved:
        print('resolved components', [(c.name,c.code,c.value_type,c.value) for c in resolved.components])
    presentations = db.price_rule_presentations()
    print('presentations', presentations)
