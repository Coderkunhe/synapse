#!/usr/bin/env python3
"""Minimal async SMTP sink — prints received emails to stdout.

Usage:
    python tools/smtp-sink.py [port]

B41: SMTP production-mode testing without external services.
Listens on localhost, accepts plain SMTP (no TLS), prints
sender/recipient/subject/body to terminal.
"""

import asyncio
import sys
from email import message_from_bytes


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle one SMTP session — minimal implementation."""
    peer = writer.get_extra_info("peername", ("?", 0))

    async def say(code: str, msg: str) -> None:
        writer.write(f"{code} {msg}\r\n".encode())
        await writer.drain()

    async def readline() -> str:
        line = await reader.readline()
        return line.decode().rstrip("\r\n")

    await say("220", "smtp-sink ready")
    sender = ""
    recipients: list[str] = []
    data_lines: list[str] = []

    while True:
        line = await readline()
        if not line:
            break
        cmd = line[:4].upper().rstrip()
        arg = line[5:] if len(line) > 4 else ""

        if cmd == "EHLO" or cmd == "HELO":
            await say("250", "ok")
        elif cmd == "MAIL":
            sender = arg.replace("FROM:", "").strip(" <>")
            await say("250", "ok")
        elif cmd == "RCPT":
            recip = arg.replace("TO:", "").strip(" <>")
            recipients.append(recip)
            await say("250", "ok")
        elif cmd == "DATA":
            await say("354", "end data with <CR><LF>.<CR><LF>")
            while True:
                data_line = await readline()
                if data_line == ".":
                    break
                data_lines.append(data_line)
            raw = "\r\n".join(data_lines)
            msg = message_from_bytes(raw.encode())

            print(f"\n{'='*60}")
            print(f"📧 From:    {msg.get('From', sender)}")
            print(f"   To:      {', '.join(recipients)}")
            print(f"   Subject: {msg.get('Subject', '(none)')}")
            print(f"   Peer:    {peer[0]}:{peer[1]}")
            print(f"{'='*60}")
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        print(part.get_payload(decode=True).decode())
            else:
                print(msg.get_payload(decode=True).decode())
            print(f"{'='*60}\n")

            await say("250", "ok")
            sender = ""
            recipients = []
            data_lines = []
        elif cmd == "QUIT":
            await say("221", "bye")
            break
        elif cmd == "RSET":
            sender = ""
            recipients = []
            data_lines = []
            await say("250", "ok")
        elif cmd == "NOOP":
            await say("250", "ok")
        else:
            await say("500", f"unknown command: {cmd}")

    writer.close()
    await writer.wait_closed()


async def main(port: int = 1025) -> None:
    server = await asyncio.start_server(
        handle_client, host="127.0.0.1", port=port
    )
    print(f"🧪 SMTP sink listening on 127.0.0.1:{port} — press Ctrl+C to stop")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1025
    asyncio.run(main(port))
