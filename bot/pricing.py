
# Tariff & Pricing Configuration

# Currency Logic: 1 RUB = 10 NC
RUB_TO_NC = 10

# Pricing for Generations (in NC)
MODEL_PRICES = {
    "imagen-4.0-fast-generate-001": 50,
    "imagen-4.0-generate-001": 100,
    "imagen-4.0-ultra-generate-001": 150,
    "gemini-2.5-flash-image": 70,
    "gemini-3-pro-image-preview": 400
}

# Extra costs (add to base price)
RESOLUTION_SURCHARGES = {
    "2K": 100, # Base 400 + 100 = 500
    "4K": 350  # Base 400 + 350 = 750 (User Request: 750 for 4K)
}

# UI Metadata
MODEL_DISPLAY = {
    "imagen-4.0-fast-generate-001": {"name": "Imagen 4 (Fast)", "family": "imagen", "short": "Fast", "supports_resolution": False, "supports_references": False, "supports_dialogue": False},
    "imagen-4.0-generate-001": {"name": "Imagen 4 (Basic)", "family": "imagen", "short": "Basic", "supports_resolution": False, "supports_references": False, "supports_dialogue": False},
    "imagen-4.0-ultra-generate-001": {"name": "Imagen 4 (Ultra)", "family": "imagen", "short": "Ultra", "supports_resolution": False, "supports_references": False, "supports_dialogue": False},
    "gemini-2.5-flash-image": {"name": "Nano Banana (Flash)", "family": "banana", "short": "Flash", "supports_resolution": False, "supports_references": True, "supports_dialogue": True},
    "gemini-3-pro-image-preview": {"name": "Nano Banana (Pro)", "family": "banana", "short": "Pro", "supports_resolution": True, "supports_references": True, "supports_dialogue": True}
}

ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4"]

# Tariff Constraints
TARIFFS = {
    "demo": {
        "price_rub": 0,
        "monthly_nc": 0,
        "initial_nc": 500,
        "allowed_models": [
            "imagen-4.0-fast-generate-001",
            "gemini-2.5-flash-image",
            "gemini-3-pro-image-preview" 
        ],
        "max_resolution": "1024x1024",
        "allowed_resolutions": ["1024x1024"],
        "max_refs": 0, # No refs
        "allowed_ar": ["1:1"], # Only square
        "can_use_2k_4k": False
    },
    "basic": {
        "price_rub": 390,
        "monthly_nc": 3000,
        "allowed_models": [
            "imagen-4.0-generate-001",
            "imagen-4.0-fast-generate-001",
            "imagen-4.0-ultra-generate-001",
            "gemini-2.5-flash-image",
            "gemini-3-pro-image-preview"
        ],
        "max_resolution": "1024x1024",
        "allowed_resolutions": ["1024x1024"],
        "max_refs": 1,
        "allowed_ar": ["*"], # All
        "can_use_2k_4k": False
    },
    "full": {
        "price_rub": 990,
        "monthly_nc": 8000,
        "allowed_models": ["*"], # All
        "max_resolution": "4K", 
        "allowed_resolutions": ["1024x1024", "2K", "4K"],
        "max_refs": 5,
        "allowed_ar": ["*"],
        "can_use_2k_4k": True
    },
    # Admin gets full access effectively, handled by logic override
    "admin": {
        "can_use_2k_4k": True,
        "max_refs": 10
    }
}

# Top-up Packages
PACKAGES = {
    "handful": {
        "name": "Горсть",
        "price_rub": 100,
        "nc": 1000,
        "bonus_percent": 0
    },
    "sack": {
        "name": "Мешок",
        "price_rub": 500,
        "nc": 5500,
        "bonus_percent": 10
    },
    "chest": {
        "name": "Сундук",
        "price_rub": 1000,
        "nc": 12000,
        "bonus_percent": 20
    },
    "treasury": {
        "name": "Казна",
        "price_rub": 5000,
        "nc": 65000,
        "bonus_percent": 30
    }
}

def calculate_cost(model: str, resolution: str) -> int:
    """Calculates the cost of a generation request."""
    base_cost = MODEL_PRICES.get(model, 100) # Default safe fallback
    
    # Handle resolution surcharge for Gemini 3 Pro
    if model == "gemini-3-pro-image-preview":
        res_upper = resolution.upper() if resolution else "1024x1024"
        if res_upper in RESOLUTION_SURCHARGES:
            base_cost += RESOLUTION_SURCHARGES[res_upper]
            
    return base_cost

def validate_request(tariff: str, model: str, resolution: str, ref_count: int, ar: str) -> tuple[bool, str]:
    """
    Checks if the request is valid for the given tariff.
    Returns (True, "") if allowed, or (False, "reason") if denied.
    """
    if tariff == 'admin':
        return True, ""
        
    rules = TARIFFS.get(tariff, TARIFFS['demo']) # Fallback to demo
    
    # 1. Model Check
    if "*" not in rules['allowed_models'] and model not in rules['allowed_models']:
        return False, f"❌ Модель {model} недоступна на тарифе {tariff.upper()}."
        
    # 2. Resolution Check (specifically for 2K/4K)
    res_upper = resolution.upper() if resolution else "1024x1024"
    if res_upper in ["2K", "4K"] and not rules['can_use_2k_4k']:
        return False, f"❌ Разрешение {res_upper} доступно только на тарифе ПОЛНЫЙ."
        
    # 3. Ref Check
    if ref_count > rules['max_refs']:
        if rules['max_refs'] == 0:
             return False, "❌ Загрузка изображений доступна с тарифа БАЗОВЫЙ."
        return False, f"❌ Тариф {tariff.upper()} позволяет максимум {rules['max_refs']} референс(ов)."
        
    # 4. AR Check
    if "*" not in rules['allowed_ar']:
        # If strict AR, check if it matches allowed (mostly 1:1)
        # We need to normalize current strict check implies only 1:1 is allowed for Demo
        if ar != "1:1":
             return False, f"❌ Тариф {tariff.upper()} поддерживает только соотношение 1:1 (квадрат)."

    return True, ""
