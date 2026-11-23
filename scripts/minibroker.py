"""A minimal MQTT 3.1.1 broker for testing (QoS 0, retained messages, one user). Admin port: PUB <topic> <payload> | DUMP."""
import asyncio
import json
import sys

USER, PASSWORD = "mate", "secret"
MQTT_PORT, ADMIN_PORT = int(sys.argv[1]), int(sys.argv[2])
retained: dict[str, str] = {}
log: list[dict] = []
clients: list = []   # (writer, set(filters))
connects: list[dict] = []


def enc_len(n):
    out = b""
    while True:
        b = n % 128
        n //= 128
        out += bytes([b | (128 if n else 0)])
        if not n:
            return out


def packet(first, body):
    return bytes([first]) + enc_len(len(body)) + body


def s(data, i):
    n = int.from_bytes(data[i:i + 2], "big")
    return data[i + 2:i + 2 + n].decode(errors="replace"), i + 2 + n


def match(flt, topic):
    a, b = flt.split("/"), topic.split("/")
    for i, x in enumerate(a):
        if x == "#":
            return True
        if i >= len(b) or (x != "+" and x != b[i]):
            return False
    return len(a) == len(b)


def deliver(topic, payload):
    body = len(topic.encode()).to_bytes(2, "big") + topic.encode() + payload.encode()
    for w, filters in clients:
        if any(match(f, topic) for f in filters):
            w.write(packet(0x30, body))


async def handle(r, w):
    entry = (w, set())
    try:
        while True:
            first = (await r.readexactly(1))[0]
            mult, n = 1, 0
            while True:
                b = (await r.readexactly(1))[0]
                n += (b & 127) * mult
                mult *= 128
                if not b & 128:
                    break
            data = await r.readexactly(n) if n else b""
            kind = first >> 4
            if kind == 1:  # CONNECT
                _, i = s(data, 0)
                flags = data[i + 1]
                i += 4
                cid, i = s(data, i)
                if flags & 4:
                    _, i = s(data, i)
                    _, i = s(data, i)
                user = pw = None
                if flags & 0x80:
                    user, i = s(data, i)
                if flags & 0x40:
                    pw, i = s(data, i)
                ok = (user, pw) == (USER, PASSWORD) if (flags & 0x80) else False
                connects.append({"client": cid, "user": user, "ok": ok, "will": bool(flags & 4)})
                w.write(packet(0x20, bytes([0, 0 if ok else 4])))
                if not ok:
                    await w.drain()
                    break
                clients.append(entry)
            elif kind == 8:  # SUBSCRIBE
                pid = data[:2]
                i, granted = 2, b""
                while i < len(data):
                    flt, i = s(data, i)
                    i += 1
                    entry[1].add(flt)
                    granted += b"\x00"
                    for t, p in retained.items():
                        if match(flt, t):
                            deliver(t, p)
                w.write(packet(0x90, pid + granted))
            elif kind == 3:  # PUBLISH (QoS 0)
                topic, i = s(data, 0)
                payload = data[i:].decode(errors="replace")
                if first & 1:
                    retained[topic] = payload
                log.append({"topic": topic, "payload": payload, "retain": bool(first & 1)})
                deliver(topic, payload)
            elif kind == 12:
                w.write(packet(0xD0, b""))
            elif kind == 14:
                break
            await w.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        if entry in clients:
            clients.remove(entry)
        w.close()


async def admin(r, w):
    line = (await r.readline()).decode().strip()
    if line.startswith("PUB "):
        _, topic, payload = line.split(" ", 2)
        deliver(topic, payload)
        w.write(b"ok\n")
    elif line == "DUMP":
        w.write((json.dumps({"retained": retained, "log": log, "connects": connects, "subscribers": len(clients)}) + "\n").encode())
    elif line == "RESET":
        log.clear(); connects.clear(); w.write(b"ok\n")
    await w.drain()
    w.close()


async def main():
    a = await asyncio.start_server(handle, "127.0.0.1", MQTT_PORT)
    b = await asyncio.start_server(admin, "127.0.0.1", ADMIN_PORT)
    print("minibroker up", flush=True)
    async with a, b:
        await asyncio.gather(a.serve_forever(), b.serve_forever())

asyncio.run(main())
