from __future__ import annotations

import argparse
import asyncio
import contextlib


async def _copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(64 * 1024):
            writer.write(data)
            await writer.drain()
    finally:
        with contextlib.suppress(Exception):
            writer.write_eof()


async def _handle(
    downstream_reader: asyncio.StreamReader,
    downstream_writer: asyncio.StreamWriter,
    target_host: str,
    target_port: int,
) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(target_host, target_port)
    except OSError:
        downstream_writer.close()
        await downstream_writer.wait_closed()
        return

    try:
        tasks = {
            asyncio.create_task(_copy(downstream_reader, upstream_writer)),
            asyncio.create_task(_copy(upstream_reader, downstream_writer)),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
    finally:
        upstream_writer.close()
        downstream_writer.close()
        await asyncio.gather(
            upstream_writer.wait_closed(),
            downstream_writer.wait_closed(),
            return_exceptions=True,
        )


async def _serve(listen_port: int, target_host: str, target_port: int) -> None:
    server = await asyncio.start_server(
        lambda reader, writer: _handle(reader, writer, target_host, target_port),
        host="0.0.0.0",  # noqa: S104 - isolated container-to-host test bridge
        port=listen_port,
    )
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ephemeral TCP bridge for isolated container tests")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(_serve(args.listen_port, args.target_host, args.target_port))


if __name__ == "__main__":
    main()
