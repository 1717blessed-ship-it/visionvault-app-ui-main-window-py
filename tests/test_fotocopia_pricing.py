"""Tests for Fotocopias y terminaciones pricing calculations."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.database.database import ImageDatabase
from app.services.fotocopia_pricing_service import FotocopiaPricingService


@pytest.fixture
def db_connection():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Initialize database schema
    db = ImageDatabase(str(db_path))

    # Ensure products table exists (migrate commercial pricing)
    db._migrate_commercial_pricing()

    # Install fotocopia price catalog
    db.install_fotocopia_price_catalog()

    # Commit changes
    db.connection.commit()

    # Yield the ImageDatabase's connection (not a separate one)
    yield db.connection

    # Close connection before cleanup
    db.connection.close()

    # Try to delete the file, ignore if still locked
    try:
        db_path.unlink()
    except PermissionError:
        pass


@pytest.fixture
def pricing_service(db_connection):
    """Create pricing service with test database."""
    return FotocopiaPricingService(db_connection)


class TestFotocopiaPricing:
    """Test photocopies pricing calculations."""

    def test_100_fotocopias_bn_simple_sin_descuento(self, pricing_service):
        """100 fotocopias B/N simples = $5.000 sin descuentos."""
        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_bn_simple",
            unit_price=50.0,
            physical_sheets=100,
            copies=1,
            is_urgent=False,
        )

        assert calculation.base_price == 5000.0
        assert calculation.discount_amount == 0.0
        assert calculation.discount_percent == 0.0
        assert calculation.surcharge_amount == 0.0
        assert calculation.final_price == 5000.0
        assert calculation.is_urgent is False

    def test_20_fotocopias_color_doble_faz(self, pricing_service):
        """20 fotocopias color doble faz = $3.600."""
        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_color_doble",
            unit_price=180.0,
            physical_sheets=20,
            copies=1,
            is_urgent=False,
        )

        assert calculation.base_price == 3600.0
        assert calculation.discount_amount == 0.0
        assert calculation.surcharge_amount == 0.0
        assert calculation.final_price == 3600.0

    @pytest.mark.parametrize(
        ("title", "product_code", "unit_price"),
        [
            ("Fotocopia B/N Simple", "fotocopia_bn_simple", 50.0),
            ("Fotocopia B/N Doble Faz", "fotocopia_bn_doble", 80.0),
            ("Fotocopia Color Simple", "fotocopia_color_simple", 120.0),
            ("Fotocopia Color Doble Faz", "fotocopia_color_doble", 180.0),
        ],
    )
    def test_catalog_price_is_resolved_by_photocopy_product(
        self, pricing_service, title, product_code, unit_price,
    ):
        """Each mode keeps its own price even though all use Papel A4."""
        assert pricing_service.product_code_for_title(title) == product_code
        calculation = pricing_service.calculate_for_product(product_code, physical_sheets=97)
        assert calculation.calculation_details["unit_price"] == unit_price
        assert calculation.final_price == unit_price * 97

    def test_fotocopia_urgente_30_porcentaje(self, pricing_service):
        """Trabajo urgente de $5.000 = $6.500 (30% surcharge)."""
        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_bn_simple",
            unit_price=50.0,
            physical_sheets=100,
            copies=1,
            is_urgent=True,
        )

        assert calculation.base_price == 5000.0
        assert calculation.surcharge_percent == 30.0
        assert calculation.surcharge_amount == 1500.0
        assert calculation.final_price == 6500.0
        assert calculation.is_urgent is True

    def test_fotocopia_con_juegos(self, pricing_service):
        """Test photocopies with multiple copies (juegos)."""
        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_bn_simple",
            unit_price=50.0,
            physical_sheets=10,
            copies=5,  # 5 juegos
            is_urgent=False,
        )

        # 10 hojas * 5 juegos * $50 = $2500
        assert calculation.base_price == 2500.0
        assert calculation.final_price == 2500.0

    def test_fotocopia_precio_manual(self, pricing_service):
        """Test manual price override."""
        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_bn_simple",
            unit_price=50.0,
            physical_sheets=100,
            copies=1,
            is_urgent=False,
            manual_price=4500.0,
        )

        assert calculation.base_price == 5000.0
        assert calculation.manual_price == 4500.0
        assert calculation.final_price == 4500.0

    def test_get_urgent_surcharge_percent(self, pricing_service):
        """Test getting urgent surcharge percentage."""
        percent = pricing_service.get_urgent_surcharge_percent()
        assert percent == 30.0  # Default is 30%


class TestAnilladoPricing:
    """Test binding (anillado) pricing calculations."""

    def test_anillado_80_hojas_mediano(self, pricing_service):
        """Anillado de 80 hojas = categoría Mediano y precio $1.800."""
        calculation = pricing_service.calculate_anillado(
            sheets=80,
            quantity=1,
            is_urgent=False,
        )

        assert calculation.base_price == 1800.0
        assert calculation.calculation_details["product_type"] == "anillado_mediano"
        assert calculation.calculation_details["sheets"] == 80
        assert calculation.calculation_details["includes_covers"] is True

    def test_anillado_chico_30_hojas(self, pricing_service):
        """Anillado chico para 30 hojas."""
        calculation = pricing_service.calculate_anillado(
            sheets=30,
            quantity=1,
            is_urgent=False,
        )

        assert calculation.base_price == 1200.0
        assert calculation.calculation_details["product_type"] == "anillado_chico"

    def test_anillado_grande_200_hojas(self, pricing_service):
        """Anillado grande para 200 hojas."""
        calculation = pricing_service.calculate_anillado(
            sheets=200,
            quantity=1,
            is_urgent=False,
        )

        assert calculation.base_price == 2500.0
        assert calculation.calculation_details["product_type"] == "anillado_grande"

    def test_anillado_supera_limite_300_hojas(self, pricing_service):
        """Anillado que supera las 300 hojas usa precio grande con advertencia."""
        calculation = pricing_service.calculate_anillado(
            sheets=350,
            quantity=1,
            is_urgent=False,
        )

        assert calculation.base_price == 2500.0  # Uses grande price
        assert calculation.calculation_details["beyond_limit"] is True

    def test_anillado_multiple_unidades(self, pricing_service):
        """Multiple binding units."""
        calculation = pricing_service.calculate_anillado(
            sheets=80,
            quantity=3,
            is_urgent=False,
        )

        assert calculation.base_price == 5400.0  # 1800 * 3

    def test_anillado_urgente(self, pricing_service):
        """Anillado urgente con recargo."""
        calculation = pricing_service.calculate_anillado(
            sheets=80,
            quantity=1,
            is_urgent=True,
        )

        assert calculation.base_price == 1800.0
        assert calculation.surcharge_amount == 540.0  # 30% of 1800
        assert calculation.final_price == 2340.0


class TestPlastificadoPricing:
    """Test laminating (plastificado) pricing calculations."""

    def test_dos_plastificados_a4(self, pricing_service):
        """Dos plastificados A4 = $3.000."""
        calculation = pricing_service.calculate_plastificado(
            quantity=2,
            is_urgent=False,
        )

        assert calculation.base_price == 3000.0
        assert calculation.final_price == 3000.0
        assert calculation.calculation_details["size"] == "A4"

    def test_plastificado_unitario(self, pricing_service):
        """Single laminated unit."""
        calculation = pricing_service.calculate_plastificado(
            quantity=1,
            is_urgent=False,
        )

        assert calculation.base_price == 1500.0

    def test_plastificado_urgente(self, pricing_service):
        """Laminating with urgent surcharge."""
        calculation = pricing_service.calculate_plastificado(
            quantity=2,
            is_urgent=True,
        )

        assert calculation.base_price == 3000.0
        assert calculation.surcharge_amount == 900.0  # 30% of 3000
        assert calculation.final_price == 3900.0


class TestQuantityDiscounts:
    """Test quantity discount system."""

    def test_sin_descuento_por_defecto(self, pricing_service):
        """By default, no discounts are configured."""
        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_bn_simple",
            unit_price=50.0,
            physical_sheets=100,
            copies=1,
            is_urgent=False,
        )

        assert calculation.discount_percent == 0.0
        assert calculation.discount_amount == 0.0

    def test_descuento_configurable(self, db_connection, pricing_service):
        """Test configurable quantity discount."""
        # Add a discount rule
        db_connection.execute(
            """INSERT INTO fotocopia_quantity_discounts
               (product_type, min_quantity, max_quantity, discount_percent, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, datetime('now'), datetime('now'))""",
            ("fotocopia_bn_simple", 50, None, 10.0)
        )
        db_connection.commit()

        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_bn_simple",
            unit_price=50.0,
            physical_sheets=100,
            copies=1,
            is_urgent=False,
        )

        assert calculation.discount_percent == 10.0
        assert calculation.discount_amount == 500.0  # 10% of 5000
        assert calculation.final_price == 4500.0

    def test_descuento_antes_recargo(self, db_connection, pricing_service):
        """Discount is applied before surcharge."""
        # Add discount
        db_connection.execute(
            """INSERT INTO fotocopia_quantity_discounts
               (product_type, min_quantity, max_quantity, discount_percent, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, datetime('now'), datetime('now'))""",
            ("fotocopia_bn_simple", 50, None, 10.0)
        )
        db_connection.commit()

        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_bn_simple",
            unit_price=50.0,
            physical_sheets=100,
            copies=1,
            is_urgent=True,
        )

        # Base: 5000
        # After 10% discount: 4500
        # After 30% surcharge: 5850
        assert calculation.base_price == 5000.0
        assert calculation.discount_amount == 500.0
        assert calculation.surcharge_amount == 1350.0  # 30% of 4500
        assert calculation.final_price == 5850.0


class TestPriceSnapshot:
    """Test price snapshot saving."""

    def test_save_price_snapshot(self, db_connection, pricing_service):
        """Test saving price calculation to order_jobs."""
        # Create an order job
        cursor = db_connection.execute(
            """INSERT INTO order_jobs (order_id, title, material, size, quantity, subtotal,
               created_at, updated_at)
               VALUES (1, 'Test', 'Fotocopia B/N', '', 100, 5000, datetime('now'), datetime('now'))"""
        )
        job_id = cursor.lastrowid

        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_bn_simple",
            unit_price=50.0,
            physical_sheets=100,
            copies=1,
            is_urgent=False,
        )

        pricing_service.save_price_snapshot(job_id, calculation)

        # Verify snapshot was saved
        row = db_connection.execute(
            "SELECT * FROM order_jobs WHERE id = ?", (job_id,)
        ).fetchone()

        assert row["base_price"] == 5000.0
        assert row["discount_amount"] == 0.0
        assert row["surcharge_amount"] == 0.0
        assert row["final_price"] == 5000.0
        assert row["is_urgent"] == 0
        assert row["manual_price"] is None

    def test_save_price_snapshot_urgente(self, db_connection, pricing_service):
        """Test saving urgent price calculation."""
        cursor = db_connection.execute(
            """INSERT INTO order_jobs (order_id, title, material, size, quantity, subtotal,
               created_at, updated_at)
               VALUES (1, 'Test', 'Fotocopia B/N', '', 100, 6500, datetime('now'), datetime('now'))"""
        )
        job_id = cursor.lastrowid

        calculation = pricing_service.calculate_fotocopia(
            product_type="fotocopia_bn_simple",
            unit_price=50.0,
            physical_sheets=100,
            copies=1,
            is_urgent=True,
        )

        pricing_service.save_price_snapshot(job_id, calculation)

        row = db_connection.execute(
            "SELECT * FROM order_jobs WHERE id = ?", (job_id,)
        ).fetchone()

        assert row["base_price"] == 5000.0
        assert row["surcharge_amount"] == 1500.0
        assert row["final_price"] == 6500.0
        assert row["is_urgent"] == 1


class TestUnitPriceRetrieval:
    """Test unit price retrieval from price_rules."""

    def test_get_unit_price_fotocopia_bn_simple(self, pricing_service):
        """Test getting unit price for B/N simple photocopy."""
        price = pricing_service._get_unit_price("fotocopia_bn_simple")
        assert price == 50.0

    def test_get_unit_price_fotocopia_bn_doble(self, pricing_service):
        """Test getting unit price for B/N double-sided photocopy."""
        price = pricing_service._get_unit_price("fotocopia_bn_doble")
        assert price == 80.0

    def test_get_unit_price_fotocopia_color_simple(self, pricing_service):
        """Test getting unit price for color simple photocopy."""
        price = pricing_service._get_unit_price("fotocopia_color_simple")
        assert price == 120.0

    def test_get_unit_price_fotocopia_color_doble(self, pricing_service):
        """Test getting unit price for color double-sided photocopy."""
        price = pricing_service._get_unit_price("fotocopia_color_doble")
        assert price == 180.0

    def test_get_unit_price_anillado_chico(self, pricing_service):
        """Test getting unit price for small binding."""
        price = pricing_service._get_unit_price("anillado_chico")
        assert price == 1200.0

    def test_get_unit_price_anillado_mediano(self, pricing_service):
        """Test getting unit price for medium binding."""
        price = pricing_service._get_unit_price("anillado_mediano")
        assert price == 1800.0

    def test_get_unit_price_anillado_grande(self, pricing_service):
        """Test getting unit price for large binding."""
        price = pricing_service._get_unit_price("anillado_grande")
        assert price == 2500.0

    def test_get_unit_price_plastificado_a4(self, pricing_service):
        """Test getting unit price for A4 laminating."""
        price = pricing_service._get_unit_price("plastificado_a4")
        assert price == 1500.0
