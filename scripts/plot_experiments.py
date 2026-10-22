import csv
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "measurements"
OUTPUT = DATA / "plots"

EXPERIMENTS = {
    "No backpressure, 1 worker": "unbounded-1",
    "Backpressure, 1 worker": "bounded-1",
    "Backpressure, 2 workers": "bounded-2-ready",
}


def read_csv(name):
    with (DATA / f"{name}.csv").open() as file:
        return list(csv.DictReader(file))


def plot_metric(column, ylabel, filename):
    fig, ax = plt.subplots(figsize=(10, 5))

    for label, name in EXPERIMENTS.items():
        rows = read_csv(name)

        times = [float(row["time_s"]) for row in rows]
        values = [float(row[column]) for row in rows]

        ax.plot(times, values, label=label)

    ax.set_xlabel("Time (seconds)")
    ax.set_ylabel(ylabel)
    ax.set_title(ylabel)
    ax.legend()
    ax.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(OUTPUT / filename, dpi=160)
    plt.close(fig)


def plot_source():
    fig, ax = plt.subplots(figsize=(10, 5))

    for label, name in EXPERIMENTS.items():
        text = (DATA / f"{name}-source.txt").read_text()

        matches = re.findall(
            r"accepted=(\d+)/40\s+rejected=\d+\s+elapsed=([\d.]+)s",
            text,
        )

        times = [0.0]
        counts = [0]

        for accepted, elapsed in matches:
            times.append(float(elapsed))
            counts.append(int(accepted))

        ax.plot(times, counts, marker="o", label=label)

    ax.set_xlabel("Time (seconds)")
    ax.set_ylabel("Published tasks")
    ax.set_title("Source publication progress")
    ax.legend()
    ax.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(OUTPUT / "source_progress.png", dpi=160)
    plt.close(fig)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    plot_metric(
        "ready",
        "Queue depth (ready messages)",
        "queue_depth.png",
    )

    plot_metric(
        "worker_mb",
        "Worker containers memory (MB)",
        "worker_memory.png",
    )

    plot_metric(
        "rabbitmq_mb",
        "RabbitMQ container memory (MB)",
        "rabbitmq_memory.png",
    )

    plot_source()

    for path in sorted(OUTPUT.glob("*.png")):
        print(f"Created: {path}")


if __name__ == "__main__":
    main()
