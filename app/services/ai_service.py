import google.generativeai as genai
from app.core.config import settings

# Configure the Gemini SDK securely
genai.configure(api_key=settings.GEMINI_API_KEY)

async def generate_productivity_insight(activity_summary_data: str) -> str:
    """Calls Gemini LLM to generate enterprise insights based on aggregated activity."""
    try:
        # Initialize the model (1.5-pro is excellent for complex analytical reasoning)
        model = genai.GenerativeModel('gemini-1.5-pro')
        
        # Structure the prompt with clear system-level instructions
        prompt = f"""
        You are an enterprise productivity analyst AI. 
        Analyze the following daily employee activity log data. 
        Provide a concise summary, highlighting periods of high focus, 
        and suggest professional improvements for any excess idle time.

        Employee Activity Data:
        {activity_summary_data}
        """
        
        # Execute the async call
        response = await model.generate_content_async(prompt)
        
        return response.text
        
    except Exception as e:
        # Graceful fallback so the dashboard doesn't crash if the API fails
        return f"AI Insight generation failed: {str(e)}"