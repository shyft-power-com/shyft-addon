import unittest
import fossil_comparison as fc


class FossilComparisonTest(unittest.TestCase):
    def test_savings(self):
        r = fc.compute_fossil_savings(20.0, 70.0, 15.0, 0.30, 1.80, 11.58, 18.0)
        gas = 70 / 0.92 * 0.1158
        fuel = 15 * fc.ICE_LITERS_PER_EV_KWH * 1.80
        self.assertAlmostEqual(r["fossil_gas_cost_eur"], round(gas, 2), places=2)
        self.assertAlmostEqual(r["fossil_fuel_cost_eur"], round(fuel, 2), places=2)
        self.assertAlmostEqual(r["savings_eur"], round(round(gas, 2) + round(fuel, 2) - 35 * 0.30, 2), places=1)

    def test_petrol_equivalent_follows_user_consumption(self):
        a = fc.compute_fossil_savings(0, 0, 10.0, 0.3, 1.8, None, 18.0)["ice_l_per_100km"]
        b = fc.compute_fossil_savings(0, 0, 10.0, 0.3, 1.8, None, 27.0)["ice_l_per_100km"]
        self.assertAlmostEqual(b / a, 1.5, places=1)
        self.assertTrue(5.5 < a < 8.0)

    def test_cop(self):
        self.assertAlmostEqual(fc.hp_cop(35, 5), 4.0)
        self.assertEqual(fc.hp_cop(200, 0), fc.COP_MIN)

    def test_missing_data(self):
        self.assertIsNone(fc.compute_fossil_savings(0, 0, 0, 0.3, 1.8, 11.0, 18.0))
        self.assertIsNone(fc.compute_fossil_savings(10, 30, 0, None, 1.8, 11.0, 18.0))
        self.assertIsNone(fc.compute_fossil_savings(10, 30, 0, 0.3, 1.8, None, 18.0))
        self.assertIsNotNone(fc.compute_fossil_savings(0, 0, 5, 0.3, 1.8, None, 18.0))

    def test_demo(self):
        self.assertEqual(fc.demo_result()["savings_eur"], 5.21)

    def test_parse(self):
        body = {"status": "success", "response": {"e10_eur_per_l": 1.79, "gas_ct_per_kwh": 11.58, "e10_updated": "x", "gas_updated": "y"}}
        self.assertEqual(fc.parse_fossil_prices_response(body)["gas_ct_per_kwh"], 11.58)
        self.assertIsNone(fc.parse_fossil_prices_response({"response": {}}))
        self.assertIsNone(fc.parse_fossil_prices_response("x"))


if __name__ == "__main__":
    unittest.main()
