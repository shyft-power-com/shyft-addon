import unittest
import fossil_comparison as fc


class FossilComparisonTest(unittest.TestCase):
    def test_savings(self):
        r = fc.compute_fossil_savings(100.0, 180.0, 0.30, 1.80, 11.58)
        gas = 100 * 3.5 / 0.92 * 0.1158
        fuel = 1000 * 7.5 / 100 * 1.80
        self.assertAlmostEqual(r["fossil_cost_eur"], round(gas + fuel, 2), places=2)
        self.assertAlmostEqual(r["savings_eur"], round(gas + fuel - 280 * 0.30, 2), places=2)
        self.assertEqual(r["km"], 1000)

    def test_missing_data(self):
        self.assertIsNone(fc.compute_fossil_savings(None, None, 0.3, 1.8, 11.0))
        self.assertIsNone(fc.compute_fossil_savings(10, 0, None, 1.8, 11.0))
        self.assertIsNone(fc.compute_fossil_savings(10, 0, 0.3, 1.8, None))
        self.assertIsNotNone(fc.compute_fossil_savings(None, 50, 0.3, 1.8, None))

    def test_parse(self):
        body = {"status": "success", "response": {"e10_eur_per_l": 1.79, "gas_ct_per_kwh": 11.58, "e10_updated": "x", "gas_updated": "y"}}
        self.assertEqual(fc.parse_fossil_prices_response(body)["gas_ct_per_kwh"], 11.58)
        self.assertIsNone(fc.parse_fossil_prices_response({"response": {}}))
        self.assertIsNone(fc.parse_fossil_prices_response("x"))


if __name__ == "__main__":
    unittest.main()
