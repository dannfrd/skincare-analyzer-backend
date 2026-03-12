import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=API_KEY)


def analyze_ingredients_with_ai(text):

    prompt = f"""
You are a skincare ingredient expert.

Analyze the following skincare ingredients:

{text}

Return:
1. list of ingredients detected
2. safety level (safe / moderate / risky)
3. explanation
"""

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )

    return response.text