import asyncio
import os
from google import genai
from config import config

async def list_models():
    client = genai.Client(api_key=config.GEMINI_API_KEY.get_secret_value())
    print("Listing models...")
    try:
        # Pager object, iterate manually
        for m in client.models.list():
            print(f"Model Name: {m.name}")
            # print(dir(m)) # Unwrap if needed
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(list_models())
