import unittest
import sys
import os

# Add bot directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bot')))

from pricing import calculate_cost, validate_request, MODEL_PRICES, RESOLUTION_SURCHARGES

class TestPricing(unittest.TestCase):

    def test_calculate_cost(self):
        # Basic models
        self.assertEqual(calculate_cost("imagen-4.0-fast-generate-001", "1024x1024"), 50)
        self.assertEqual(calculate_cost("gemini-2.5-flash-image", "1024x1024"), 70)
        
        # Pro model scaling
        # Base
        self.assertEqual(calculate_cost("gemini-3-pro-image-preview", "1024x1024"), 400)
        # 2K
        self.assertEqual(calculate_cost("gemini-3-pro-image-preview", "2K"), 500)
        # 4K
        self.assertEqual(calculate_cost("gemini-3-pro-image-preview", "4K"), 750)
        
        # Case Insensitivity
        self.assertEqual(calculate_cost("gemini-3-pro-image-preview", "4k"), 750)

    def test_demo_constraints(self):
        tariff = "demo"
        
        # Allowed Model
        valid, _ = validate_request(tariff, "gemini-2.5-flash-image", "1024x1024", 0, "1:1")
        self.assertTrue(valid)
        
        # Disallowed Ref
        valid, msg = validate_request(tariff, "gemini-2.5-flash-image", "1024x1024", 1, "1:1")
        self.assertFalse(valid)
        self.assertIn("доступна с тарифа БАЗОВЫЙ", msg)
        
        # Disallowed AR
        valid, msg = validate_request(tariff, "gemini-2.5-flash-image", "1024x1024", 0, "16:9")
        self.assertFalse(valid)
        self.assertIn("только соотношение 1:1", msg)
        
        # Disallowed Res
        valid, msg = validate_request(tariff, "gemini-3-pro-image-preview", "4K", 0, "1:1")
        self.assertFalse(valid)
        self.assertIn("только на тарифе ПОЛНЫЙ", msg)

    def test_basic_constraints(self):
        tariff = "basic"
        
        # Allowed Refs (1)
        valid, _ = validate_request(tariff, "gemini-2.5-flash-image", "1024x1024", 1, "16:9")
        self.assertTrue(valid)
        
        # Disallowed Refs (2)
        valid, msg = validate_request(tariff, "gemini-2.5-flash-image", "1024x1024", 2, "16:9")
        self.assertFalse(valid)
        self.assertIn("максимум 1", msg)
        
        # Disallowed Res (4K)
        valid, msg = validate_request(tariff, "gemini-3-pro-image-preview", "4K", 0, "1:1")
        self.assertFalse(valid)
        self.assertIn("только на тарифе ПОЛНЫЙ", msg)

    def test_full_constraints(self):
        tariff = "full"
        
        # Allowed 4K
        valid, _ = validate_request(tariff, "gemini-3-pro-image-preview", "4K", 0, "16:9")
        self.assertTrue(valid)
        
        # Allowed Refs (5)
        valid, _ = validate_request(tariff, "gemini-3-pro-image-preview", "1024x1024", 5, "16:9")
        self.assertTrue(valid)
        
        # Disallowed Refs (6)
        valid, msg = validate_request(tariff, "gemini-3-pro-image-preview", "1024x1024", 6, "16:9")
        self.assertFalse(valid)

if __name__ == '__main__':
    unittest.main()
