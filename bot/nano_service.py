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
            "nano_banana": "gemini-2.0-flash-exp-image-generation",
            "nano_banana_pro": "models/gemini-2.0-pro-exp-02-05", # Using 2.0 Pro Experimental
            "imagen": "imagen-4.0-fast-generate-001"
        }

    async def generate_image(self, prompt: str, aspect_ratio: str = "1:1", resolution: str = "1024x1024", model_type: str = "nano_banana_pro", reference_images: list = None) -> tuple[bytes, int]:
        """
        Generate an image using the Gemini API.
        Returns: (image_bytes, token_count)
        Supported model_types: 'nano_banana', 'nano_banana_pro', 'imagen'.
        """
        self.logger.info(f"Requests generation ({model_type}): prompt='{prompt}', refs={len(reference_images) if reference_images else 0}")
        
        target_model = self.models.get(model_type, self.models["nano_banana_pro"])

        try:
            # Config construction based on model
            image_config_args = {"aspect_ratio": aspect_ratio}
            
            # Simplified config for now
            if model_type == "nano_banana_pro" and resolution:
                # Try to parse "1024x1024"
                try:
                    w, h = map(int, resolution.lower().split('x'))
                    # image_config_args["width"] = w
                    # image_config_args["height"] = h
                    pass 
                except:
                    pass
            
            config_args = types.GenerateContentConfig(
                response_modalities=['IMAGE'],
                image_config=types.ImageConfig(**image_config_args)
            )

            # Prepare contents
            contents = [prompt]
            if reference_images:
                for img_bytes in reference_images:
                    try:
                        # Convert bytes to PIL Image (Gemini SDK usually likes PIL or specific Part types)
                        # We use PIL here as it's safe
                        img = Image.open(BytesIO(img_bytes))
                        contents.append(img)
                    except Exception as e:
                        self.logger.error(f"Failed to process ref image: {e}")
            
            # Run blocking SDK call in executor
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=target_model,
                contents=contents,
                config=config_args
            )
            
            token_count = 0
            if response.usage_metadata:
                token_count = response.usage_metadata.total_token_count

            for part in response.parts:
                if part.inline_data:
                    return part.inline_data.data, token_count
            
            raise Exception("No image in response")

        except Exception as e:
            self.logger.error(f"Generation failed: {e}")
            raise e

nano_service = NanoBananaService()
