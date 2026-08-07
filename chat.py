# local Ollama model chat.py
import asyncio

# Tools whose output is already final, user-ready text (no synthesis needed).
# The 8B local model unreliably reproduces tool output verbatim through a second
# generation pass, so for these we display the result directly instead of asking
# the model to relay it — see PLAN.md quality-pass notes for why.
PASSTHROUGH_TOOLS = {"get_procedure_checklist"}

import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv

load_dotenv()

MODEL = "llama3.1:8b"
SERVER_PARAMS = StdioServerParameters(command="uv", args=["run", "python", "server.py"])

SYSTEM_PROMPT = (
    "You are a bureaucracy assistant for international students in Stuttgart. "
    "Use search_bureaucracy_docs for open-ended questions, and get_procedure_checklist "
    "when the user wants the full step-by-step procedure for a known topic.\n\n"
    "MOST IMPORTANT RULE: when a tool returns a result, your reply MUST reproduce that "
    "tool result's content in full — every step, every fact, every number — word for "
    "word. You may add a short one-sentence intro before it, but never shorten, "
    "summarize, or drop any part of the tool result itself.\n\n"
    "Never estimate, round, or fill gaps from your own knowledge — use only what the "
    "tool returned. If a tool result includes a 'Source:'/'URL:' line, keep it in your "
    "reply exactly as given; if it doesn't, do not invent one."
)


def mcp_tools_to_ollama(mcp_tools) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in mcp_tools
    ]


async def run_chat():
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tools = mcp_tools_to_ollama(tools_result.tools)
            print(f"Connected. Available tools: {[t['function']['name'] for t in tools]}\n")

            messages = []
            while True:
                user_input = input("You: ").strip()
                if user_input.lower() in {"exit", "quit"}:
                    break

                messages.append({"role": "user", "content": user_input})

                while True:
                    response = ollama.chat(
                        model=MODEL,
                        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                        tools=tools,
                    )
                    msg = response["message"]
                    messages.append(msg)

                    if not msg.get("tool_calls"):
                        print(f"\nOllama: {msg['content']}\n")
                        break

                    passthrough_result = None
                    for call in msg["tool_calls"]:
                        name = call["function"]["name"]
                        args = call["function"]["arguments"]
                        print(f"[calling tool: {name}({args})]")
                        result = await session.call_tool(name, args)
                        result_text = "\n".join(
                            c.text for c in result.content if c.type == "text"
                        )
                        messages.append({"role": "tool", "content": result_text})
                        if name in PASSTHROUGH_TOOLS:
                            passthrough_result = result_text

                    if passthrough_result is not None:
                        print(f"\nOllama: {passthrough_result}\n")
                        break


if __name__ == "__main__":
    asyncio.run(run_chat())