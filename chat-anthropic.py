import asyncio

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

MODEL = "claude-sonnet-4-5"
SERVER_PARAMS = StdioServerParameters(command="uv", args=["run", "python", "server.py"])


def mcp_tools_to_anthropic(mcp_tools) -> list[dict]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in mcp_tools
    ]


async def run_chat():
    anthropic_client = Anthropic()

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tools = mcp_tools_to_anthropic(tools_result.tools)
            print(f"Connected. Available tools: {[t['name'] for t in tools]}\n")

            messages = []
            while True:
                user_input = input("You: ").strip()
                if user_input.lower() in {"exit", "quit"}:
                    break

                messages.append({"role": "user", "content": user_input})

                while True:
                    response = anthropic_client.messages.create(
                        model=MODEL,
                        max_tokens=1024,
                        tools=tools,
                        messages=messages,
                    )
                    messages.append({"role": "assistant", "content": response.content})

                    if response.stop_reason != "tool_use":
                        for block in response.content:
                            if block.type == "text":
                                print(f"\nClaude: {block.text}\n")
                        break

                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            print(f"[calling tool: {block.name}({block.input})]")
                            result = await session.call_tool(block.name, block.input)
                            result_text = "\n".join(
                                c.text for c in result.content if c.type == "text"
                            )
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result_text,
                                }
                            )
                    messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    asyncio.run(run_chat())