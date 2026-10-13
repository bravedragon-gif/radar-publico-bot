"""Fail closed: do not publish unverified weekly news."""
import asyncio

def generate_briefing():
    raise RuntimeError('Publicação bloqueada: coletor de fontes oficiais ainda não implementado')

async def main():
    generate_briefing()

if __name__ == '__main__':
    asyncio.run(main())
