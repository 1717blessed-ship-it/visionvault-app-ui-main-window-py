"""Fast PDF colour detection and print quotation helpers.

The rasterization is deliberately low resolution: it is sufficient to detect
colour ink coverage while keeping the quote responsive for multi-page PDFs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class PdfPageAnalysis:
    page_number: int
    is_color: bool
    color_coverage_percent: float
    ink_coverage_percent: float = 100.0


@dataclass(frozen=True, slots=True)
class PdfPrintQuote:
    pages: tuple[PdfPageAnalysis, ...]
    copies: int
    duplex: bool
    quantities: dict[str, int]
    total: float

    @property
    def color_pages(self) -> int:
        return sum(page.is_color for page in self.pages)


class PdfPrintAnalysisService:
    """Classify PDF pages and quote them with the current photocopy prices."""

    # A coloured pixel must have noticeable chroma.  Near-neutral grays do not
    # count as colour even when PDF rendering creates tiny RGB differences.
    CHROMA_THRESHOLD = 18
    INK_THRESHOLD = 245
    # Una página solo se cobra como color cuando al menos este porcentaje de
    # su área impresa contiene color real. Evita cobrar logos o detalles mínimos
    # como una impresión color completa.
    COLOR_PAGE_THRESHOLD_PERCENT = 10.0
    BLANK_SHEET_PRICE = 30.0

    def analyze(self, pdf_path: str | Path) -> tuple[PdfPageAnalysis, ...]:
        try:
            import fitz  # PyMuPDF
        except ImportError as error:  # pragma: no cover - depends on installation
            raise RuntimeError("Falta PyMuPDF. Instalá las dependencias para analizar PDFs.") from error

        document = fitz.open(str(pdf_path))
        try:
            result: list[PdfPageAnalysis] = []
            for index, page in enumerate(document):
                # 72 dpi is fast and samples enough of photos, logos and fills.
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), colorspace=fitz.csRGB, alpha=False)
                samples = memoryview(pixmap.samples)
                colored = ink = samples_count = 0
                # Sample every fourth pixel to cap CPU work on large page sizes.
                for offset in range(0, len(samples), 12):
                    samples_count += 1
                    red, green, blue = samples[offset], samples[offset + 1], samples[offset + 2]
                    if min(red, green, blue) < self.INK_THRESHOLD:
                        ink += 1
                        if max(red, green, blue) - min(red, green, blue) >= self.CHROMA_THRESHOLD:
                            colored += 1
                coverage = (colored / ink * 100.0) if ink else 0.0
                ink_coverage = (ink / samples_count * 100.0) if samples_count else 0.0
                result.append(PdfPageAnalysis(
                    index + 1,
                    coverage >= self.COLOR_PAGE_THRESHOLD_PERCENT,
                    round(coverage, 2),
                    round(ink_coverage, 2),
                ))
            return tuple(result)
        finally:
            document.close()

    def quote(
        self,
        pages: Iterable[PdfPageAnalysis],
        *,
        copies: int,
        duplex: bool,
        unit_prices: dict[str, float],
    ) -> PdfPrintQuote:
        if copies < 1:
            raise ValueError("La cantidad de copias debe ser al menos 1.")
        page_list = tuple(pages)
        quantities: Counter[str] = Counter()
        step = 2 if duplex else 1
        for start in range(0, len(page_list), step):
            sides = page_list[start:start + step]
            # Una hoja se vende a $30 solamente si sus caras están por completo
            # en blanco. Cualquier uso de tinta se cotiza como B/N o color.
            if all(page.ink_coverage_percent == 0 for page in sides):
                quantities["hoja_simple"] += copies
                continue
            color = any(page.is_color for page in sides)
            if duplex and len(sides) == 2:
                product = "fotocopia_color_doble" if color else "fotocopia_bn_doble"
            else:
                product = "fotocopia_color_simple" if color else "fotocopia_bn_simple"
            quantities[product] += copies
        total = sum(
            (self.BLANK_SHEET_PRICE if product == "hoja_simple" else unit_prices.get(product, 0.0)) * quantity
            for product, quantity in quantities.items()
        )
        return PdfPrintQuote(page_list, copies, duplex, dict(quantities), round(total, 2))

    def quote_documents(
        self,
        documents: Iterable[Iterable[PdfPageAnalysis]],
        *,
        copies: int,
        duplex: bool,
        unit_prices: dict[str, float],
    ) -> PdfPrintQuote:
        """Cotiza varios PDFs sin unir sus hojas al calcular doble faz."""
        if copies < 1:
            raise ValueError("La cantidad de copias debe ser al menos 1.")

        all_pages: list[PdfPageAnalysis] = []
        quantities: Counter[str] = Counter()
        total = 0.0
        for document_pages in documents:
            document_quote = self.quote(
                document_pages,
                copies=copies,
                duplex=duplex,
                unit_prices=unit_prices,
            )
            all_pages.extend(document_quote.pages)
            quantities.update(document_quote.quantities)
            total += document_quote.total
        return PdfPrintQuote(tuple(all_pages), copies, duplex, dict(quantities), round(total, 2))
