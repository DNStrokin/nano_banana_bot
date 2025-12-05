import asyncio
import logging
import base64
from io import BytesIO
from google import genai
from google.genai import types
from PIL import Image
from config import config

class NanoBananaService:
    def __init__(self):
        self.logger = logging.getLogger("NanoBanana")
        self.client = genai.Client(api_key=config.GEMINI_API_KEY.get_secret_value())
        # Mapping generic names to specific models
        self.models = {
            "nano_banana": "gemini-2.5-flash-image",
            "nano_banana_pro": "gemini-3-pro-image-preview",
            "imagen": "imagen-3.0-generate-001"
        }

    async def generate_image(self, prompt: str, aspect_ratio: str = "1:1", resolution: str = "1024x1024", model_type: str = "nano_banana_pro") -> bytes:
        """
        Generate an image using the Gemini API.
        Supported model_types: 'nano_banana', 'nano_banana_pro', 'imagen'.
        """
        self.logger.info(f"Requests generation ({model_type}): prompt='{prompt}'")
        
        target_model = self.models.get(model_type, self.models["nano_banana_pro"])

        try:
            # Config construction based on model
            image_config_args = {"aspect_ratio": aspect_ratio}
            
            # Gemini 2.5 Flash / Nano Banana supports limited resolutions (usually handled by AR)
            # Gemini 3 Pro / Nano Banana Pro supports 'image_size' or 'resolution'
            # Imagen 3 supports specific aspect ratios
            
            # Simplified config for now
            if model_type == "nano_banana_pro":
                # Pro supports resolution param (e.g. '2K')? SDK might want 'image_size'
                pass
            
            config_args = types.GenerateContentConfig(
                response_modalities=['IMAGE'],
                image_config=types.ImageConfig(**image_config_args)
            )
            
            # Run blocking SDK call in executor
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=target_model,
                contents=[prompt],
                config=config_args
            )
            
            for part in response.parts:
                if part.inline_data:
                    # In a real app we might upload this to S3/Cloudinary or send directly to TG
                    # Here we assume the calling code in main.py will handle the bytes
                    # But wait, aiogram sends URL or InputFile. 
                    # Let's save to a temp file or return Bytes
                    return part.inline_data.data # This is base64 bytes usually or raw bytes?
                    # The SDK documentation says part.as_image() returns PIL Image.
                    # part.inline_data.data is the raw bytes.
            
            raise Exception("No image in response")

        except Exception as e:
            self.logger.error(f"Generation failed: {e}")
            raise e

nano_service = NanoBananaService()
