import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --------------------------------------------------
# Load data
# --------------------------------------------------
data_ai = pd.read_csv('DQN_sched.csv')
data_ai['time'] = pd.to_datetime(data_ai['time'])

# --------------------------------------------------
# Frame indexing
# --------------------------------------------------
data_ai['frame'] = data_ai.groupby('rnti').cumcount()

# --------------------------------------------------
# Start from first frame where all UEs are present
# --------------------------------------------------
num_ues_total = data_ai['rnti'].nunique()
ue_counts_per_frame = data_ai.groupby('frame')['rnti'].nunique()

valid_frames = ue_counts_per_frame[ue_counts_per_frame == num_ues_total].index
if len(valid_frames) == 0:
    raise ValueError("No frame contains all UEs.")

start_frame = valid_frames[0]

data_ai = data_ai[data_ai['frame'] >= start_frame].copy()
data_ai['frame'] -= start_frame

# --------------------------------------------------
# Per-UE throughput per frame
# --------------------------------------------------
ue_rate_per_frame = data_ai.groupby(['frame', 'rnti'])['throughput'].sum()
pivot_ue_frame = ue_rate_per_frame.unstack().fillna(0)

# --------------------------------------------------
# Per-UE buffer per frame
# --------------------------------------------------
ue_buffer_per_frame = data_ai.groupby(['frame', 'rnti'])['dl_bs'].sum()
pivot_buffer_frame = ue_buffer_per_frame.unstack().fillna(0)

# --------------------------------------------------
# Cell-level metrics
# --------------------------------------------------
cell_throughput_per_frame = data_ai.groupby('frame')['cell_throughput'].first()
fairness_per_frame = data_ai.groupby('frame')['fairness'].first()
total_buffer_per_frame = data_ai.groupby('frame')['dl_bs'].sum()

# --------------------------------------------------
# Jain fairness recomputation (optional)
# --------------------------------------------------
def jain_fairness(row):
    rates = row.values.astype(float)
    num = np.sum(rates) ** 2
    den = len(rates) * np.sum(rates ** 2)
    return np.nan if den == 0 else num / den

jain_from_throughput = pivot_ue_frame.apply(jain_fairness, axis=1)

# --------------------------------------------------
# Plot 1: UE throughput per frame
# --------------------------------------------------
num_ues = len(pivot_ue_frame.columns)
fig, axes = plt.subplots(num_ues, 1, figsize=(12, 2.5 * num_ues), sharex=True)

if num_ues == 1:
    axes = [axes]

for ax, ue in zip(axes, pivot_ue_frame.columns):
    ax.plot(pivot_ue_frame.index, pivot_ue_frame[ue])
    ax.set_ylabel('Mbps')
    ax.set_title(f'UE {ue} Throughput')
    ax.grid(True)

axes[-1].set_xlabel('Frame')
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Plot 2: cell throughput
# --------------------------------------------------
plt.figure(figsize=(12, 5))
plt.plot(cell_throughput_per_frame.index, cell_throughput_per_frame.values)
plt.xlabel('Frame')
plt.ylabel('Cell Throughput [Mbps]')
plt.title('Cell Throughput Evolution')
plt.grid(True)
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Plot 3: fairness
# --------------------------------------------------
plt.figure(figsize=(12, 5))
plt.plot(fairness_per_frame.index, fairness_per_frame.values, label='Logged')
plt.plot(jain_from_throughput.index, jain_from_throughput.values, linestyle='--', label='Recomputed')
plt.xlabel('Frame')
plt.ylabel('Fairness')
plt.title('Fairness Evolution')
plt.ylim(0, 1.05)
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Plot 4: throughput vs fairness
# --------------------------------------------------
fig, ax1 = plt.subplots(figsize=(12, 5))

ax1.plot(cell_throughput_per_frame.index, cell_throughput_per_frame.values, label='Throughput')
ax1.set_xlabel('Frame')
ax1.set_ylabel('Throughput [Mbps]')
ax1.grid(True)

ax2 = ax1.twinx()
ax2.plot(fairness_per_frame.index, fairness_per_frame.values, linestyle='--', label='Fairness')
ax2.set_ylabel('Fairness')
ax2.set_ylim(0, 1.05)

plt.title('Throughput vs Fairness')
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Plot 5: average throughput per UE
# --------------------------------------------------
avg_rate_per_ue = pivot_ue_frame.mean()

plt.figure(figsize=(8, 5))
plt.bar(avg_rate_per_ue.index.astype(str), avg_rate_per_ue.values)
plt.xlabel('UE ID')
plt.ylabel('Average Throughput [Mbps]')
plt.title('Average Throughput per UE')
plt.grid(True, axis='y')
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Plot 6: cumulative throughput per UE
# --------------------------------------------------
cum_rates = pivot_ue_frame.cumsum()

plt.figure(figsize=(12, 6))
for ue in cum_rates.columns:
    plt.plot(cum_rates.index, cum_rates[ue], label=f'UE {ue}')

plt.xlabel('Frame')
plt.ylabel('Cumulative Throughput [Mb]')
plt.title('Cumulative Throughput per UE')
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()

# ==================================================
# BUFFER ANALYSIS
# ==================================================

# --------------------------------------------------
# Plot 7: UE buffer evolution
# --------------------------------------------------
num_ues = len(pivot_buffer_frame.columns)
fig, axes = plt.subplots(num_ues, 1, figsize=(12, 2.5 * num_ues), sharex=True)

if num_ues == 1:
    axes = [axes]

for ax, ue in zip(axes, pivot_buffer_frame.columns):
    ax.plot(pivot_buffer_frame.index, pivot_buffer_frame[ue])
    ax.set_ylabel('Buffer')
    ax.set_title(f'UE {ue} Buffer')
    ax.grid(True)

axes[-1].set_xlabel('Frame')
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Plot 8: total buffer
# --------------------------------------------------
plt.figure(figsize=(12, 5))
plt.plot(total_buffer_per_frame.index, total_buffer_per_frame.values)
plt.xlabel('Frame')
plt.ylabel('Total DL Buffer')
plt.title('Total Buffer Evolution')
plt.grid(True)
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Plot 9: throughput vs buffer (time)
# --------------------------------------------------
fig, ax1 = plt.subplots(figsize=(12, 5))

ax1.plot(cell_throughput_per_frame.index, cell_throughput_per_frame.values)
ax1.set_xlabel('Frame')
ax1.set_ylabel('Throughput [Mbps]')
ax1.grid(True)

ax2 = ax1.twinx()
ax2.plot(total_buffer_per_frame.index, total_buffer_per_frame.values, linestyle='--')
ax2.set_ylabel('Total Buffer')

plt.title('Throughput vs Buffer')
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Plot 10: scatter buffer vs throughput
# --------------------------------------------------
plt.figure(figsize=(7, 5))
plt.scatter(total_buffer_per_frame.values, cell_throughput_per_frame.values, alpha=0.4)
plt.xlabel('Total Buffer')
plt.ylabel('Throughput [Mbps]')
plt.title('Throughput vs Buffer')
plt.grid(True)
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Plot 11: scatter buffer vs fairness
# --------------------------------------------------
plt.figure(figsize=(7, 5))
plt.scatter(total_buffer_per_frame.values, fairness_per_frame.values, alpha=0.4)
plt.xlabel('Total Buffer')
plt.ylabel('Fairness')
plt.title('Fairness vs Buffer')
plt.grid(True)
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Stats
# --------------------------------------------------
print("Avg throughput:", cell_throughput_per_frame.mean())
print("Avg fairness:", fairness_per_frame.mean())
print("Avg buffer:", total_buffer_per_frame.mean())

print("Corr(buffer, throughput):", total_buffer_per_frame.corr(cell_throughput_per_frame))
print("Corr(buffer, fairness):", total_buffer_per_frame.corr(fairness_per_frame))