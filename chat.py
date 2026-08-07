# local Ollama model chat.py
import asyncio

import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv

load_dotenv()

MODEL = "llama3.1:8b"
SERVER_PARAMS = StdioServerParameters(command="uv", args=["run", "python", "server.py"])

SYSTEM_PROMPT = (
    "You are a bureaucracy assistant for international students in Stuttgart. "
    "Always call search_bureaucracy_docs before answering questions about procedures, "
    "requirements, fees, or addresses. Answer ONLY using the retrieved text — never "
    "estimate, round, or fill gaps from your own knowledge. If the retrieved chunks "
    "don't contain the specific figure or fact asked for, say so explicitly and suggest "
    "the user verify with the official source. Always cite the source title and URL."
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

                    for call in msg["tool_calls"]:
                        name = call["function"]["name"]
                        args = call["function"]["arguments"]
                        print(f"[calling tool: {name}({args})]")
                        result = await session.call_tool(name, args)
                        result_text = "\n".join(
                            c.text for c in result.content if c.type == "text"
                        )
                        messages.append({"role": "tool", "content": result_text})


if __name__ == "__main__":
    asyncio.run(run_chat())