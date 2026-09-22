"""Google ADK entrypoint. The ADK development interface discovers root_agent."""




from app.router import build_router_agent

root_agent = build_router_agent()