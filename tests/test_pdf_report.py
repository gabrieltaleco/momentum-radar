import unittest

from src.pdf_report import ascii_text, concise_quality_message, wrap, wrapped_end_y


class PdfReportLayoutTests(unittest.TestCase):
    def test_unicode_symbols_are_replaced_with_readable_ascii(self):
        self.assertEqual(ascii_text("Ação → nova · score ≥ 80"), "Acao -> nova / score >= 80")

    def test_legacy_mojibake_is_repaired_before_pdf_rendering(self):
        self.assertEqual(ascii_text("cÃ³digo"), "codigo")

    def test_provider_json_is_reduced_to_a_readable_quality_message(self):
        message = concise_quality_message({"message": 'yahoo_finance: HTTP 404: {"description":"No data found"}'})
        self.assertEqual(message, "Ticker sem dados no provider; confirmar simbolo e bolsa.")

    def test_wrapped_guide_action_starts_after_the_last_description_line(self):
        width = 225
        description = (
            "Arista Networks esta a negociar muito acima do seu padrao. "
            "Como o impulso esta forte, o movimento pode incluir interesse e vendas nervosas; "
            "o radar nao consegue chamar isto de panic sell sem dados adicionais."
        )
        description_y = 500
        description_lines = wrap(description, max(12, int(width / max(4.2, 8 * 0.48))))
        last_description_y = description_y - (len(description_lines) - 1) * 11
        action_y = wrapped_end_y(description_y, description, width, 8, 11) - 10

        self.assertGreaterEqual(len(description_lines), 4)
        self.assertLessEqual(action_y, last_description_y - 10)


if __name__ == "__main__":
    unittest.main()
