"""Fixed-target TLS byte relay; no CONNECT, target selection, credentials or HTTP logic."""

import asyncio
import re
import sys


async def serve(target):
    async def connected(reader, writer):
        upstream = None
        tasks = []
        try:
            remote, upstream = await asyncio.wait_for(asyncio.open_connection(target, 18443), 5)

            async def pump(source, destination):
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()

            tasks = [
                asyncio.create_task(pump(reader, upstream)),
                asyncio.create_task(pump(remote, writer)),
            ]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=600)
        except (OSError, asyncio.TimeoutError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            if upstream:
                upstream.close()

    server = await asyncio.start_server(connected, "0.0.0.0", 18443)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    target = sys.argv[1]
    if not re.fullmatch(r"wk-live-[a-f0-9]{10}-db", target):
        raise SystemExit("isolated database namespace required")
    asyncio.run(serve(target))
