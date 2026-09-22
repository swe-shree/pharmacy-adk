from google.adk.agents import LlmAgent

from app.appointment.tools import APPOINTMENT_TOOLS
from app.config.settings import get_settings

appointment_agent = LlmAgent(name="appointment_agent", model=get_settings().large_model, description="Buyer-side appointment agent.", instruction="Handle doctor search, availability, booking, rescheduling, cancellation, and status. Use tools and never invent medical or appointment data.", tools=APPOINTMENT_TOOLS)