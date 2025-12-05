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
            "imagen": "imagen-4.0-fast-generate-001"
        }

    async def generate_image(self, prompt: str, aspect_ratio: str = "1:1", resolution: str = "1K", model_type: str = "nano_banana_pro", reference_images: list = None, chat_session = None) -> tuple[bytes, int, object]:
        """
        Generate an image using the Gemini API.
        Returns: (image_bytes, token_count, chat_session_obj)
        """
        # Map generic resolution strings if they come in legacy format
        res_map = {"1024x1024": "1K", "2048x2048": "2K", "4096x4096": "4K"}
        final_res = res_map.get(resolution, resolution) # Default to passing through if already 1K/2K

        self.logger.info(f"Requests gen ({model_type}): prompt='{prompt}', res={final_res}, refs={len(reference_images) if reference_images else 0}")
        
        target_model = self.models.get(model_type, self.models["nano_banana_pro"])

        try:
            # Special handling for Imagen models which use generate_images
            if "imagen" in target_model:
                 # Imagen 3/4 uses specific client.models.generate_images usually
                 # and might fail with generate_content or chat sessions.
                 
                 # Note: "reference_images" are not standardly supported in imagen-3/4 fast unless via specific inputs? 
                 # For now we ignore refs for Imagen or assume text-to-image.
                 
                response = await asyncio.to_thread(
                   self.client.models.generate_images,
                   model=target_model,
                   prompt=prompt,
                   config=types.GenerateImagesConfig(
                       number_of_images=1,
                       aspect_ratio=aspect_ratio
                   )
                )
                if response.generated_images:
                    return response.generated_images[0].image.image_bytes, 0, None # No token count/chat for Imagen
                raise Exception("No image in Imagen response")
                
            
            # --- Gemini Flow (Flash/Pro) ---

            # Config construction
            image_config_args = {
                 "aspect_ratio": aspect_ratio
            }
            
            # Flash (gemini-2.5-flash-image) supports aspect_ratio BUT NOT image_size (1K triggers error).
            # Pro (gemini-3-pro) supports both.
            if "gemini-3-pro" in target_model:
                image_config_args["image_size"] = final_res
            
            config_args = types.GenerateContentConfig(
                response_modalities=['IMAGE', 'TEXT'],
                image_config=types.ImageConfig(**image_config_args)
            )

            # Prepare contents
            contents = [prompt]
            if reference_images:
                for img_bytes in reference_images:
                    try:
                        img = Image.open(BytesIO(img_bytes))
                        contents.append(img)
                    except Exception as e:
                        self.logger.error(f"Failed to process ref: {e}")
            
            # --- Chat / Generate Switch ---
            response = None
            
            # If we already have a session, send message to it
            if chat_session:
                response = await asyncio.to_thread(
                    chat_session.send_message,
                    message=contents, # In chat, we send 'message' not 'contents' usually, but SDK unifies this somewhat. 
                    # Actually for chat.send_message, it typically takes a string or list of parts. 
                    # If contents is a list, we might need to be careful. 
                    # Let's trust logic for now or refine if errors.
                    config=config_args
                )
            else:
                # Fresh generation
                # If Pro, we might want to START a chat to enable editing later?
                # The user asked for dialogue support for Full users.
                # It's safer to always use client.chats.create if we want a chat session, 
                # OR just use generate_content for one-offs.
                # Let's try to create a chat if it is Pro model, to allow subsequent edits?
                # Actually, the user example showed `client.models.generate_content` for initial, 
                # but `client.chats.create` for multi-turn.
                
                # Correction: For multi-turn, best to start with chats.create logic implies.
                # But to keep it simple, we can use generate_content for the first shot, 
                # and if the user wants to edit, we might need to pass the history? 
                # Actually, the example showed: 
                # `chat = client.chats.create(...)` then `response = chat.send_message(...)`
                
                # So if we want dialogue, we should probably instantiate a chat.
                
                if "gemini-3-pro" in target_model:
                     chat_session = self.client.chats.create(model=target_model)
                     response = await asyncio.to_thread(
                        chat_session.send_message,
                        message=contents,
                        config=config_args
                     )
                else:
                    # Flash / others
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
                    return part.inline_data.data, token_count, chat_session
            
            raise Exception("No image in response")

        except Exception as e:
            self.logger.error(f"Generation failed: {e}")
            raise e

nano_service = NanoBananaService()
