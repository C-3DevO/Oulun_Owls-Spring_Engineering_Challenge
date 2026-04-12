import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --------------------------------------------------
# Jain fairness from per-UE throughput
# --------------------------------------------------
def jain_fairness(row):
    rates = row.values.astype(float)
    numerator = np.sum(rates) ** 2
    denominator = len(rates) * np.sum(rates ** 2)
    if denominator == 0:
        return np.nan
    return numerator / denominator

# --------------------------------------------------
# Process one scheduler log
# Assumptions:
# - each frame contains each RNTI once
# - columns available: time, rnti, throughput, dl_bs, cell_throughput, fairness
# --------------------------------------------------
def process_scheduler(file_path, name):
    data = pd.read_csv(file_path)

    if 'time' in data.columns:
        data['time'] = pd.to_datetime(data['time'])

    # Frame indexing:
    # the 1st appearance of each RNTI belongs to frame 0,
    # the 2nd appearance to frame 1, etc.
    data['frame'] = data.groupby('rnti').cumcount()

    # Keep only frames where all UEs are present
    num_ues_total = data['rnti'].nunique()
    ue_counts_per_frame = data.groupby('frame')['rnti'].nunique()

    valid_frames = ue_counts_per_frame[ue_counts_per_frame == num_ues_total].index
    if len(valid_frames) == 0:
        raise ValueError(f"{name}: No frame contains all UEs.")

    start_frame = valid_frames[0]
    data = data[data['frame'] >= start_frame].copy()
    data['frame'] = data['frame'] - start_frame

    # Per-UE throughput per frame
    ue_rate_per_frame = data.groupby(['frame', 'rnti'])['throughput'].sum()
    pivot_ue_frame = ue_rate_per_frame.unstack().fillna(0)

    # Per-UE buffer per frame
    ue_buffer_per_frame = data.groupby(['frame', 'rnti'])['dl_bs'].sum()
    pivot_buffer_frame = ue_buffer_per_frame.unstack().fillna(0)

    # Cell-level metrics
    cell_throughput_per_frame = data.groupby('frame')['cell_throughput'].first()
    fairness_per_frame = data.groupby('frame')['fairness'].first()
    total_buffer_per_frame = data.groupby('frame')['dl_bs'].sum()

    # Recomputed Jain fairness from UE throughputs
    jain_per_frame = pivot_ue_frame.apply(jain_fairness, axis=1)

    # UE-level summary
    avg_throughput_per_ue = pivot_ue_frame.mean()
    avg_buffer_per_ue = pivot_buffer_frame.mean()

    return {
        'name': name,
        'data': data,
        'ue_throughput': pivot_ue_frame,
        'ue_buffer': pivot_buffer_frame,
        'cell_throughput': cell_throughput_per_frame,
        'logged_fairness': fairness_per_frame,
        'jain_fairness': jain_per_frame,
        'total_buffer': total_buffer_per_frame,
        'avg_throughput_per_ue': avg_throughput_per_ue,
        'avg_buffer_per_ue': avg_buffer_per_ue
    }

# --------------------------------------------------
# Load all schedulers
# --------------------------------------------------
schedulers = [
    process_scheduler('DQN_sched.csv', 'DQN'),
    process_scheduler('ai_sched.csv', 'AI'),
    process_scheduler('rr_sched.csv', 'RR'),
    process_scheduler('qos_sched.csv', 'QoS')
]

# --------------------------------------------------
# Optional: align comparison to common frame length
# so all schedulers are compared over the same horizon
# --------------------------------------------------
min_frames = min(len(s['cell_throughput']) for s in schedulers)

for s in schedulers:
    s['cell_throughput'] = s['cell_throughput'].iloc[:min_frames]
    s['logged_fairness'] = s['logged_fairness'].iloc[:min_frames]
    s['jain_fairness'] = s['jain_fairness'].iloc[:min_frames]
    s['total_buffer'] = s['total_buffer'].iloc[:min_frames]

# --------------------------------------------------
# Individual plots for each scheduler
# --------------------------------------------------
for s in schedulers:
    name = s['name']
    ue_tp = s['ue_throughput']
    ue_buf = s['ue_buffer']
    cell_tp = s['cell_throughput']
    fairness = s['logged_fairness']
    jain = s['jain_fairness']
    total_buf = s['total_buffer']

    # Plot 1: UE throughput per frame
    num_ues = len(ue_tp.columns)
    fig, axes = plt.subplots(num_ues, 1, figsize=(12, 2.5 * num_ues), sharex=True)

    if num_ues == 1:
        axes = [axes]

    for ax, ue in zip(axes, ue_tp.columns):
        ax.plot(ue_tp.index[:len(ue_tp)], ue_tp[ue].values)
        ax.set_ylabel('Mbps')
        ax.set_title(f'{name} - UE {ue} Throughput')
        ax.grid(True)

    axes[-1].set_xlabel('Frame')
    plt.tight_layout()
    plt.show()

    # Plot 2: Cell throughput
    plt.figure(figsize=(12, 5))
    plt.plot(cell_tp.index, cell_tp.values)
    plt.xlabel('Frame')
    plt.ylabel('Cell Throughput [Mbps]')
    plt.title(f'{name} - Cell Throughput Evolution')
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Plot 3: Fairness
    plt.figure(figsize=(12, 5))
    plt.plot(fairness.index, fairness.values, label='Logged')
    plt.plot(jain.index, jain.values, linestyle='--', label='Recomputed Jain')
    plt.xlabel('Frame')
    plt.ylabel('Fairness')
    plt.title(f'{name} - Fairness Evolution')
    plt.ylim(0, 1.05)
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Plot 4: Throughput vs Fairness over time
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.plot(cell_tp.index, cell_tp.values)
    ax1.set_xlabel('Frame')
    ax1.set_ylabel('Throughput [Mbps]')
    ax1.grid(True)

    ax2 = ax1.twinx()
    ax2.plot(fairness.index, fairness.values, linestyle='--')
    ax2.set_ylabel('Fairness')
    ax2.set_ylim(0, 1.05)

    plt.title(f'{name} - Throughput vs Fairness')
    plt.tight_layout()
    plt.show()

    # Plot 5: Average throughput per UE
    plt.figure(figsize=(8, 5))
    plt.bar(s['avg_throughput_per_ue'].index.astype(str), s['avg_throughput_per_ue'].values)
    plt.xlabel('UE ID')
    plt.ylabel('Average Throughput [Mbps]')
    plt.title(f'{name} - Average Throughput per UE')
    plt.grid(True, axis='y')
    plt.tight_layout()
    plt.show()

    # Plot 6: Cumulative throughput per UE
    cum_tp = ue_tp.cumsum()
    plt.figure(figsize=(12, 6))
    for ue in cum_tp.columns:
        plt.plot(cum_tp.index, cum_tp[ue], label=f'UE {ue}')
    plt.xlabel('Frame')
    plt.ylabel('Cumulative Throughput [Mb]')
    plt.title(f'{name} - Cumulative Throughput per UE')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

    # Plot 7: UE buffer per frame
    num_ues = len(ue_buf.columns)
    fig, axes = plt.subplots(num_ues, 1, figsize=(12, 2.5 * num_ues), sharex=True)

    if num_ues == 1:
        axes = [axes]

    for ax, ue in zip(axes, ue_buf.columns):
        ax.plot(ue_buf.index[:len(ue_buf)], ue_buf[ue].values)
        ax.set_ylabel('Buffer')
        ax.set_title(f'{name} - UE {ue} Buffer')
        ax.grid(True)

    axes[-1].set_xlabel('Frame')
    plt.tight_layout()
    plt.show()

    # Plot 8: Total buffer
    plt.figure(figsize=(12, 5))
    plt.plot(total_buf.index, total_buf.values)
    plt.xlabel('Frame')
    plt.ylabel('Total DL Buffer')
    plt.title(f'{name} - Total Buffer Evolution')
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Plot 9: Throughput vs Buffer over time
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.plot(cell_tp.index, cell_tp.values)
    ax1.set_xlabel('Frame')
    ax1.set_ylabel('Throughput [Mbps]')
    ax1.grid(True)

    ax2 = ax1.twinx()
    ax2.plot(total_buf.index, total_buf.values, linestyle='--')
    ax2.set_ylabel('Total Buffer')

    plt.title(f'{name} - Throughput vs Buffer')
    plt.tight_layout()
    plt.show()

    # Plot 10: Scatter total buffer vs throughput
    plt.figure(figsize=(7, 5))
    plt.scatter(total_buf.values, cell_tp.values, alpha=0.4)
    plt.xlabel('Total Buffer')
    plt.ylabel('Throughput [Mbps]')
    plt.title(f'{name} - Throughput vs Buffer')
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Plot 11: Scatter total buffer vs fairness
    plt.figure(figsize=(7, 5))
    plt.scatter(total_buf.values, fairness.values, alpha=0.4)
    plt.xlabel('Total Buffer')
    plt.ylabel('Fairness')
    plt.title(f'{name} - Fairness vs Buffer')
    plt.grid(True)
    plt.tight_layout()
    plt.show()

# --------------------------------------------------
# Comparison plots across schedulers
# --------------------------------------------------

# Plot A: Cell throughput comparison
plt.figure(figsize=(12, 6))
for s in schedulers:
    plt.plot(s['cell_throughput'].index, s['cell_throughput'].values, label=s['name'])
plt.xlabel('Frame')
plt.ylabel('Cell Throughput [Mbps]')
plt.title('Scheduler Comparison - Cell Throughput')
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()

# Plot B: Logged fairness comparison
plt.figure(figsize=(12, 6))
for s in schedulers:
    plt.plot(s['logged_fairness'].index, s['logged_fairness'].values, label=s['name'])
plt.xlabel('Frame')
plt.ylabel('Fairness')
plt.title('Scheduler Comparison - Logged Fairness')
plt.ylim(0, 1.05)
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()

# Plot C: Recomputed Jain fairness comparison
plt.figure(figsize=(12, 6))
for s in schedulers:
    plt.plot(s['jain_fairness'].index, s['jain_fairness'].values, label=s['name'])
plt.xlabel('Frame')
plt.ylabel('Jain Fairness')
plt.title('Scheduler Comparison - Recomputed Jain Fairness')
plt.ylim(0, 1.05)
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()

# Plot D: Total buffer comparison
plt.figure(figsize=(12, 6))
for s in schedulers:
    plt.plot(s['total_buffer'].index, s['total_buffer'].values, label=s['name'])
plt.xlabel('Frame')
plt.ylabel('Total DL Buffer')
plt.title('Scheduler Comparison - Total Buffer')
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()

# Plot E: Throughput vs fairness tradeoff using averages
plt.figure(figsize=(7, 6))
for s in schedulers:
    avg_tp = s['cell_throughput'].mean()
    avg_fair = s['logged_fairness'].mean()
    plt.scatter(avg_tp, avg_fair, s=100, label=s['name'])
    plt.text(avg_tp, avg_fair, f" {s['name']}")
plt.xlabel('Average Cell Throughput [Mbps]')
plt.ylabel('Average Fairness')
plt.title('Scheduler Comparison - Average Throughput vs Fairness')
plt.ylim(0, 1.05)
plt.grid(True)
plt.tight_layout()
plt.show()

# Plot F: Frame-wise throughput vs fairness scatter
plt.figure(figsize=(7, 6))
for s in schedulers:
    plt.scatter(s['cell_throughput'].values, s['logged_fairness'].values, alpha=0.35, label=s['name'])
plt.xlabel('Cell Throughput [Mbps]')
plt.ylabel('Fairness')
plt.title('Scheduler Comparison - Throughput vs Fairness')
plt.ylim(0, 1.05)
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()

# --------------------------------------------------
# Summary table
# --------------------------------------------------
summary_rows = []

for s in schedulers:
    row = {
        'Scheduler': s['name'],
        'Avg Throughput [Mbps]': s['cell_throughput'].mean(),
        'Std Throughput [Mbps]': s['cell_throughput'].std(),
        'Avg Logged Fairness': s['logged_fairness'].mean(),
        'Std Logged Fairness': s['logged_fairness'].std(),
        'Avg Recomputed Jain': s['jain_fairness'].mean(),
        'Avg Total Buffer': s['total_buffer'].mean(),
        'Max Total Buffer': s['total_buffer'].max(),
        'Corr(Buffer, Throughput)': s['total_buffer'].corr(s['cell_throughput']),
        'Corr(Buffer, Fairness)': s['total_buffer'].corr(s['logged_fairness'])
    }
    summary_rows.append(row)

summary_df = pd.DataFrame(summary_rows)

print("\n===== Scheduler Comparison Summary =====")
print(summary_df.to_string(index=False))