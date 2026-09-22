from google.adk.agents import LlmAgent

from app.config.settings import get_settings
from app.merchant.tools import MERCHANT_TOOLS

merchant_agent = LlmAgent(name="merchant_agent", model=get_settings().large_model, description="Merchant-side pharmacy operations agent.", instruction="Handle only merchant profile, catalog, inventory, orders, fulfillment, and analytics. Never expose buyer operations or invent merchant data.", tools=MERCHANT_TOOLS)