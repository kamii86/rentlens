import csv
from datetime import datetime
from pathlib import Path

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

matplotlib.use("Agg")

root = Path(__file__).resolve().parents[1]
data_path = root / "measurements" / "task_durations.csv"
output_path = root / "measurements" / "plots" / "task_durations.png"

with data_path.open(newline="") as file:
    rows = list(csv.DictReader(file))

if not rows:
    raise ValueError("No task durations found")

times = [datetime.fromisoformat(row["created_at"]) for row in rows]
durations = [float(row["duration_seconds"]) for row in rows]

average = sum(durations) / len(durations)

fig, ax = plt.subplots(figsize=(12, 5))

ax.scatter(
    times,
    durations,
    s=18,
    alpha=0.7,
    label="Task duration",
)

ax.axhline(
    average,
    linestyle="--",
    label=f"Average: {average:.2f} s",
)

locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
ax.xaxis.set_major_locator(locator)
ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

ax.set_xlabel("Task creation time (UTC)")
ax.set_ylabel("Processing duration (seconds)")
ax.set_title("Task processing duration over time")
ax.legend()
ax.grid(alpha=0.3)

fig.tight_layout()
output_path.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(output_path, dpi=160)
plt.close(fig)

print(f"Created: {output_path}")
