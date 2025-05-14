import asyncio, sys
from pathlib import Path
from agent_shell.core.registry import Registry
from agent_shell.core.runtime import Runtime
from agent_shell.core.schema import Turn

async def main():
    reg = Registry(); reg.load_providers(Path(__file__).parent)
    rt = Runtime(reg)
    while (text := input(">> ")):
        async for msg in rt.run(Turn(user_input=text)):
            print(msg.content, end="", flush=True)
        print()

if __name__ == "__main__":
    asyncio.run(main())