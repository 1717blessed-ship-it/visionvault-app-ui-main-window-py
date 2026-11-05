from __future__ import annotations

from math import ceil

from ..models.cost_analysis_result import CostAnalysisResult, CostComponentResult, ProductivePlanchaAnalysis
from ..models.cost_component import CostComponent
from ..models.cost_rule import CostRule
from ..models.cost_condition import CostCondition
from .condition_evaluator import ConditionEvaluator


class CostCalculator:
    """Calcula métricas financieras para una regla de costo de forma independiente de la interfaz."""

    @staticmethod
    def calculate(rule: CostRule, sale_price: float = 0.0, quantity: int = 1, hours: float = 0.0, surface: float = 0.0, suggested_price: float | None = None, context: dict | None = None) -> CostAnalysisResult:
        if not rule.active:
            return CostAnalysisResult(
                rule_name=rule.name,
                product_type=rule.product_type,
                suggested_price=float(suggested_price or 0.0),
                profitability_status="loss",
                warnings=["La regla está inactiva"],
            )

        context = context or {}
        if rule.conditions and not all(
            ConditionEvaluator.matches(context, condition.field, condition.operator, condition.value)
            for condition in rule.conditions
        ):
            return CostAnalysisResult(
                rule_name=rule.name,
                rule_id=rule.id,
                product_type=rule.product_type,
                suggested_price=float(suggested_price or sale_price or 0.0),
                profitability_status="not_applicable",
                warnings=["La regla no aplica al contexto indicado"],
            )

        sale_price = max(float(sale_price or 0), 0.0)
        quantity = max(int(quantity or 1), 1)
        hours = max(float(hours or 0), 0.0)
        surface = max(float(surface or 0), 0.0)
        suggested_price = float(suggested_price or sale_price or 0.0)

        components: list[CostComponentResult] = []
        total = 0.0
        for component in rule.components:
            if not component.enabled:
                continue
            amount = component.evaluate(sale_price=sale_price, quantity=quantity, hours=hours, surface=surface)
            total += amount
            components.append(
                CostComponentResult(
                    name=component.name,
                    code=component.code or component.name,
                    value_type=component.value_type,
                    value=component.value,
                    amount=round(amount, 2),
                )
            )

        gross_profit = round(suggested_price - total, 2)
        margin_percentage = round((gross_profit / suggested_price * 100) if suggested_price else 0.0, 2)
        markup_percentage = round((gross_profit / total * 100) if total > 0 else 0.0, 2)

        profitability_status = "loss"
        warnings: list[str] = []
        if total <= 0:
            profitability_status = "no_costs" if gross_profit > 0 else "loss"
            if total <= 0:
                warnings.append("Sin costos configurados")
        elif margin_percentage >= rule.minimum_margin:
            profitability_status = "profitable"
        elif margin_percentage > 0:
            profitability_status = "margin_low"
            warnings.append("Margen por debajo del mínimo esperado")
        else:
            warnings.append("El precio no cubre los costos")

        return CostAnalysisResult(
            rule_name=rule.name,
            rule_id=rule.id,
            product_type=rule.product_type,
            suggested_price=suggested_price,
            cost_total=round(total, 2),
            gross_profit=gross_profit,
            margin_percentage=margin_percentage,
            markup_percentage=markup_percentage,
            profitability_status=profitability_status,
            warnings=warnings,
            components=components,
        )

    @staticmethod
    def recommended_price(rule: CostRule, quantity: int = 1, hours: float = 0.0, surface: float = 0.0, target_margin: float = 20.0) -> float:
        target_margin = float(target_margin or 0)
        if not 0 <= target_margin < 100:
            raise ValueError("El margen objetivo debe estar entre 0 y menor que 100")
        direct_cost = CostCalculator.calculate(rule, sale_price=0.0, quantity=quantity, hours=hours, surface=surface).cost_total
        sale_percentage = sum(
            float(component.value or 0) / 100.0
            for component in rule.components
            if component.enabled and component.value_type == "percentage"
        )
        denominator = 1 - (target_margin / 100.0) - sale_percentage
        if direct_cost <= 0 or denominator <= 0:
            return 0.0
        return round(float(direct_cost) / denominator, 2)

    @staticmethod
    def calculate_plancha_a4(context: dict, settings: dict) -> ProductivePlanchaAnalysis:
        """Calcula precio y costo de una plancha A4 con reglas productivas.

        ``context`` contiene valores del pedido; ``settings`` llega de la
        configuración persistente. Mantenerlo libre de SQLite permite probarlo
        y reutilizarlo desde pedidos, presupuestos o producción.
        """
        def number(key: str, default: float = 0.0) -> float:
            try:
                return max(0.0, float(context.get(key, default) or default))
            except (TypeError, ValueError):
                return default

        def setting(key: str, default: float) -> float:
            try:
                return max(0.0, float(settings.get(key, default) or default))
            except (TypeError, ValueError):
                return default

        quantity = max(1, int(number("quantity", 1)))
        design_minutes = [max(0.0, float(value or 0)) for value in context.get("design_minutes", [])]
        unique_designs = max(1, int(number("unique_designs", len(design_minutes) or 1)))
        if not design_minutes:
            design_minutes = [number("design_minutes_total", setting("standard_design_minutes", 10.0)) / unique_designs] * unique_designs
        elif len(design_minutes) < unique_designs:
            design_minutes.extend([setting("standard_design_minutes", 10.0)] * (unique_designs - len(design_minutes)))

        standard_design = setting("standard_design_minutes", 10.0)
        standard_print = setting("standard_print_minutes", 10.0)
        standard_cut = setting("standard_cut_minutes", 10.0)
        production_mode = str(context.get("production_mode") or "individual").strip().lower()
        production_mode = "batch" if production_mode in {"batch", "tanda", "en_tanda"} else "individual"
        batch_enabled = bool(settings.get("batch_efficiency_enabled", False))
        standard_print_total = standard_print * quantity
        standard_cut_total = standard_cut * quantity
        if production_mode == "batch" and batch_enabled:
            print_default = setting("batch_print_setup_minutes", standard_print) + setting("batch_print_incremental_minutes", 1.0) * quantity
            cut_default = setting("batch_cut_setup_minutes", standard_cut) + setting("batch_cut_incremental_minutes", 1.0) * quantity
        else:
            print_default, cut_default = standard_print_total, standard_cut_total
        print_minutes = number("print_minutes", print_default)
        cut_minutes = number("cut_minutes", cut_default)
        design_total = sum(design_minutes)
        total_minutes = design_total + print_minutes + cut_minutes

        design_blocks = sum(ceil(max(0.0, minutes - standard_design) / max(1.0, setting("additional_design_block_minutes", 10.0))) for minutes in design_minutes)
        design_surcharge = design_blocks * setting("additional_design_block_rate", 1000.0)
        productive_surcharge = number("productive_surcharge")
        additional_services = number("additional_services")
        authorized_discount = number("authorized_discount")
        base_unit_price = number("base_price", setting("base_price", 5000.0))
        base_price = base_unit_price * quantity
        suggested_price = max(0.0, base_price + design_surcharge + productive_surcharge + additional_services - authorized_discount)

        manual_price = context.get("manual_price")
        applied_value = context.get("applied_price", manual_price)
        try:
            applied_price = max(0.0, float(applied_value)) if applied_value is not None and applied_value != "" else None
        except (TypeError, ValueError):
            applied_price = None
        manual_price = applied_price if manual_price is not None else None
        price_source = "manual" if manual_price is not None else (str(context.get("price_source") or ("suggested" if applied_price is None else "base")))

        raw_material = setting("standard_raw_material_cost", 635.0) * quantity
        labor = setting("labor_hour_rate", 1800.0) * total_minutes / 60.0
        standard_labor = setting("labor_hour_rate", 1800.0) * (design_total + standard_print_total + standard_cut_total) / 60.0
        overhead = setting("standard_overhead_cost", 465.0) * quantity
        additional_materials = number("additional_materials")
        waste = number("waste_cost")
        internal_incidents = number("internal_incident_cost")
        productive_cost = raw_material + labor + overhead + additional_materials + waste + internal_incidents
        standard_productive_cost = raw_material + standard_labor + overhead + additional_materials + waste + internal_incidents
        customer_kind = str(context.get("customer_kind") or "first_purchase").strip().lower()
        commercial_cost = setting("commercial_cost_recurrent", 300.0) if customer_kind in {"recurrent", "recurrente"} else setting("commercial_cost_first_purchase", 500.0)
        final_cost = productive_cost + commercial_cost

        if internal_incidents > 0:
            classification = "internal_incident"
        elif bool(context.get("valid_productive_exception")) and (print_minutes > standard_print * quantity or cut_minutes > standard_cut * quantity):
            classification = "special_production"
        elif any(minutes > 20 for minutes in design_minutes):
            classification = "complex_design"
        elif any(minutes > standard_design for minutes in design_minutes):
            classification = "extended_design"
        else:
            classification = "standard"

        productive_profit = suggested_price - productive_cost
        final_profit = suggested_price - final_cost
        productive_margin = productive_profit / suggested_price * 100 if suggested_price else 0.0
        final_margin = final_profit / suggested_price * 100 if suggested_price else 0.0
        markup = final_profit / final_cost * 100 if final_cost else 0.0
        applied_productive_profit = applied_price - productive_cost if applied_price is not None else None
        applied_final_profit = applied_price - final_cost if applied_price is not None else None
        applied_productive_margin = applied_productive_profit / applied_price * 100 if applied_price else 0.0 if applied_price is not None else None
        applied_final_margin = applied_final_profit / applied_price * 100 if applied_price else 0.0 if applied_price is not None else None
        warnings = []
        if internal_incidents:
            warnings.append("Las incidencias internas aumentan el costo real, no el precio sugerido.")
        if suggested_price < final_cost:
            warnings.append("El precio sugerido no cubre el costo final estimado.")
        if applied_price is not None and applied_price < suggested_price:
            warnings.append("El precio aplicado es inferior al sugerido y reduce el margen esperado.")
        if applied_final_profit is not None and applied_final_profit < 0:
            warnings.append("El precio aplicado no cubre el costo final estimado del pedido.")
        return ProductivePlanchaAnalysis(
            quantity=quantity, unique_designs=unique_designs, production_mode=production_mode,
            classification=classification, estimated_design_minutes=round(design_total, 2),
            estimated_print_minutes=round(print_minutes, 2), estimated_cut_minutes=round(cut_minutes, 2),
            estimated_total_minutes=round(total_minutes, 2), base_price=round(base_price, 2),
            base_price_source=str(context.get("base_price_source") or "legacy"),
            base_price_rule_id=context.get("base_price_rule_id"), base_price_version=str(context.get("base_price_version") or ""),
            design_surcharge=round(design_surcharge, 2), productive_surcharge=round(productive_surcharge, 2),
            additional_services=round(additional_services, 2), authorized_discount=round(authorized_discount, 2),
            suggested_price=round(suggested_price, 2), applied_price=round(applied_price, 2) if applied_price is not None else None,
            manual_price=round(manual_price, 2) if manual_price is not None else None, price_source=price_source,
            productive_cost=round(productive_cost, 2), standard_productive_cost=round(standard_productive_cost, 2),
            quantity_adjusted_productive_cost=round(productive_cost, 2), estimated_batch_savings=round(max(0.0, standard_productive_cost - productive_cost), 2),
            raw_material_cost=round(raw_material + additional_materials + waste, 2), labor_cost=round(labor, 2),
            overhead_cost=round(overhead, 2), internal_incident_cost=round(internal_incidents, 2),
            commercial_cost=round(commercial_cost, 2), final_cost=round(final_cost, 2),
            productive_profit=round(productive_profit, 2), final_profit=round(final_profit, 2),
            productive_margin_percentage=round(productive_margin, 2), final_margin_percentage=round(final_margin, 2),
            applied_productive_profit=round(applied_productive_profit, 2) if applied_productive_profit is not None else None,
            applied_final_profit=round(applied_final_profit, 2) if applied_final_profit is not None else None,
            applied_productive_margin_percentage=round(applied_productive_margin, 2) if applied_productive_margin is not None else None,
            applied_final_margin_percentage=round(applied_final_margin, 2) if applied_final_margin is not None else None,
            markup_percentage=round(markup, 2), profitability_status="profitable" if final_profit > 0 else ("margin_low" if final_profit == 0 else "loss"), warnings=warnings,
        )
