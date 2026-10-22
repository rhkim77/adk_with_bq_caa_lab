"""Sample ADK Agent for testing ADK Web UI (Tools, Events, and Trace View)."""

from datetime import datetime, timezone
from google.adk.agents import LlmAgent


def get_weather(city: str) -> dict:
  """Returns the current weather information for a specified city.

  Args:
      city: The name of the city (e.g., 'Seoul', 'San Francisco', 'Tokyo').
  """
  weather_db = {
      'seoul': {'condition': 'Sunny', 'temp_c': 18, 'humidity': '45%'},
      'san francisco': {
          'condition': 'Partly Cloudy',
          'temp_c': 15,
          'humidity': '68%',
      },
      'tokyo': {'condition': 'Clear', 'temp_c': 20, 'humidity': '50%'},
  }
  key = city.strip().lower()
  data = weather_db.get(
      key, {'condition': 'Sunny', 'temp_c': 21, 'humidity': '50%'}
  )
  return {
      'status': 'success',
      'city': city,
      'weather': data['condition'],
      'temperature_celsius': data['temp_c'],
      'humidity': data['humidity'],
      'checked_at_utc': datetime.now(timezone.utc).isoformat(),
  }


def estimate_gemini_cost(
    input_tokens: int, output_tokens: int, model_tier: str = 'flash'
) -> dict:
  """Estimates token cost in USD and KRW for Gemini Enterprise / Vertex AI calls.

  Args:
      input_tokens: Number of prompt input tokens.
      output_tokens: Number of completion output tokens.
      model_tier: 'flash' or 'pro'.
  """
  rates = {
      'flash': {'input_per_1m': 0.15, 'output_per_1m': 0.60},
      'pro': {'input_per_1m': 1.25, 'output_per_1m': 10.00},
  }
  tier = rates.get(model_tier.lower(), rates['flash'])
  usd_cost = (input_tokens / 1_000_000) * tier['input_per_1m'] + (
      output_tokens / 1_000_000
  ) * tier['output_per_1m']
  krw_cost = usd_cost * 1380.0
  return {
      'status': 'success',
      'model_tier': model_tier,
      'input_tokens': input_tokens,
      'output_tokens': output_tokens,
      'estimated_usd': round(usd_cost, 6),
      'estimated_krw': round(krw_cost, 2),
  }


root_agent = LlmAgent(
    model='gemini-2.5-flash',
    name='sample_agent',
    description=(
        'Helpful assistant with weather lookup and Gemini token cost estimation'
        ' tools.'
    ),
    instruction=(
        'You are an AI assistant running on Google ADK Web UI.\n'
        '- Use `get_weather` when asked about weather conditions in any city.\n'
        '- Use `estimate_gemini_cost` when asked to calculate LLM token'
        ' costs.\n'
        '- Respond clearly and concisely in the language used by the user.'
    ),
    tools=[get_weather, estimate_gemini_cost],
)
