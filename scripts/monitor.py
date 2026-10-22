import argparse
import base64
import csv
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen


def memory_mb(value):
    match = re.match(r"([\d.]+)\s*(\w+)", value.split("/")[0].strip())
    if not match:
        return 0.0

    number, unit = match.groups()
    factors = {
        "B": 1 / 1048576,
        "KiB": 1 / 1024,
        "MiB": 1,
        "GiB": 1024,
        "kB": 1000 / 1048576,
        "MB": 1000000 / 1048576,
        "GB": 1000000000 / 1048576,
    }
    return round(float(number) * factors.get(unit, 0), 2)


def container_memory():
    result = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )

    values = {"rabbitmq": 0.0, "worker": 0.0, "app": 0.0}

    for line in result.stdout.splitlines():
        if "|" not in line:
            continue

        name, raw = line.split("|", 1)

        for service in values:
            if name.startswith(f"rentlens-{service}-"):
                values[service] += memory_mb(raw)

    return values


def read_queue(mode):
    authorization = base64.b64encode(b"rentlens:rentlens").decode()
    request = Request(
        f"http://127.0.0.1:15672/api/queues/%2F/rentlens.tasks.{mode}",
        headers={"Authorization": f"Basic {authorization}"},
    )

    with urlopen(request, timeout=5) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--mode", choices=["bounded", "unbounded"], default="bounded")
    parser.add_argument("--seconds", type=int, default=100)
    args = parser.parse_args()

    Path("measurements").mkdir(exist_ok=True)
    path = Path("measurements") / f"{args.label}.csv"

    fields = [
        "time_s",
        "ready",
        "unacked",
        "total",
        "publish_rate",
        "ack_rate",
        "rabbitmq_mb",
        "worker_mb",
        "app_mb",
    ]

    start = time.monotonic()
    last_time = start
    last_published = None

    print(f"Monitoring: {path}", flush=True)

    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()

        while time.monotonic() - start < args.seconds:
            cycle = time.monotonic()

            try:
                queue = read_queue(args.mode)
                memory = container_memory()
                now = time.monotonic()
                stats = queue.get("message_stats") or {}
                published = stats.get("publish")

                rate = 0.0
                if (
                    published is not None
                    and last_published is not None
                    and now > last_time
                ):
                    rate = max(0, (published - last_published) / (now - last_time))

                if published is not None:
                    last_published = published

                last_time = now

                row = {
                    "time_s": round(now - start, 2),
                    "ready": queue.get("messages_ready", 0),
                    "unacked": queue.get("messages_unacknowledged", 0),
                    "total": queue.get("messages", 0),
                    "publish_rate": round(rate, 2),
                    "ack_rate": (stats.get("ack_details") or {}).get("rate", 0),
                    "rabbitmq_mb": memory["rabbitmq"],
                    "worker_mb": memory["worker"],
                    "app_mb": memory["app"],
                }

                writer.writerow(row)
                stream.flush()

            except Exception as error:
                print(f"Measurement error: {error}", flush=True)

            time.sleep(max(0, 2 - (time.monotonic() - cycle)))

    print(f"Saved: {path}", flush=True)


if __name__ == "__main__":
    main()
