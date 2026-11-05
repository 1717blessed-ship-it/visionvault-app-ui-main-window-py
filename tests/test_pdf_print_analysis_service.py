from app.services.pdf_print_analysis_service import PdfPageAnalysis, PdfPrintAnalysisService


def test_quote_simple_counts_each_colored_page():
    pages = [PdfPageAnalysis(1, False, 0), PdfPageAnalysis(2, True, 25), PdfPageAnalysis(3, False, 0)]
    quote = PdfPrintAnalysisService().quote(pages, copies=2, duplex=False, unit_prices={
        "fotocopia_bn_simple": 50, "fotocopia_color_simple": 120,
    })
    assert quote.quantities == {"fotocopia_bn_simple": 4, "fotocopia_color_simple": 2}
    assert quote.total == 440


def test_quote_duplex_uses_color_duplex_when_any_side_is_color():
    pages = [PdfPageAnalysis(1, False, 0), PdfPageAnalysis(2, True, 8), PdfPageAnalysis(3, False, 0)]
    quote = PdfPrintAnalysisService().quote(pages, copies=1, duplex=True, unit_prices={
        "fotocopia_color_doble": 180, "fotocopia_bn_simple": 50,
    })
    assert quote.quantities == {"fotocopia_color_doble": 1, "fotocopia_bn_simple": 1}
    assert quote.total == 230


def test_color_threshold_is_ten_percent():
    service = PdfPrintAnalysisService()
    assert service.COLOR_PAGE_THRESHOLD_PERCENT == 10.0


def test_only_blank_sheets_are_quoted_as_twenty_peso_sheets():
    pages = [
        PdfPageAnalysis(1, False, 0, 0.0),
        PdfPageAnalysis(2, False, 0, 0.0),
    ]
    quote = PdfPrintAnalysisService().quote(pages, copies=2, duplex=True, unit_prices={})
    assert quote.quantities == {"hoja_simple": 2}
    assert quote.total == 60


def test_low_coverage_black_is_still_quoted_as_black_and_white():
    pages = [PdfPageAnalysis(1, False, 0, 4.0)]
    quote = PdfPrintAnalysisService().quote(
        pages, copies=1, duplex=False, unit_prices={"fotocopia_bn_simple": 50}
    )
    assert quote.quantities == {"fotocopia_bn_simple": 1}
    assert quote.total == 50


def test_quote_documents_keeps_duplex_pairs_within_each_pdf():
    documents = [
        [PdfPageAnalysis(1, False, 0, 10.0)],
        [PdfPageAnalysis(1, True, 30, 10.0)],
    ]
    quote = PdfPrintAnalysisService().quote_documents(
        documents,
        copies=1,
        duplex=True,
        unit_prices={"fotocopia_bn_simple": 50, "fotocopia_color_simple": 120},
    )
    assert quote.quantities == {"fotocopia_bn_simple": 1, "fotocopia_color_simple": 1}
    assert quote.total == 170
