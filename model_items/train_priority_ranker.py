import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from tqdm import tqdm
from scipy.stats import spearmanr


# ============================================================
# CONFIG
# ============================================================

RR_FILE = "RR_clean.csv"
QOS_FILE = "QOS_clean.csv"

MODEL_FILE = "priority_ranker_rr_qos.pth"

STATE_SIZE = 5
BATCH_SIZE = 2048
EPOCHS = 30
LR = 0.001

MAX_PRBS = 51.0

# ============================================================
# LOAD DATA
# ============================================================

rr = pd.read_csv(RR_FILE)
qos = pd.read_csv(QOS_FILE)

print("=" * 80)
print("RR + QoS PRIORITY RANKER")
print("=" * 80)

print(f"RR rows  : {len(rr):,}")
print(f"QoS rows : {len(qos):,}")

# ============================================================
# FEATURE PREPARATION
# ============================================================

def prepare(df):

    df = df.copy()

    df["buffer_log"] = np.log1p(df["buffer"])
    df["avg_rate_log"] = np.log1p(df["avg_rate"])
    df["estimated_rate_log"] = np.log1p(df["estimated_rate"])
    df["pf_metric_log"] = np.log1p(df["pf_metric"])

    return df

rr = prepare(rr)
qos = prepare(qos)

data = pd.concat([rr, qos], ignore_index=True)

print(f"\nTraining samples : {len(data):,}")

# ============================================================
# STATE
# ============================================================

STATE_FEATURES = [
    "reported_cqi",
    "buffer_log",
    "avg_rate_log",
    "estimated_rate_log",
    "pf_metric_log",
]

X = data[STATE_FEATURES].to_numpy(dtype=np.float32)

# ============================================================
# NORMALIZATION
# ============================================================

X[:,0] /= 15.0
X[:,1] /= 16.2
X[:,2] /= 7.3
X[:,3] /= 8.7
X[:,4] /= 5.5

# ============================================================
# BUILD PAIRWISE TRAINING SET
# ============================================================

from tqdm import tqdm

print("\n" + "=" * 80)
print("BUILDING PAIRWISE TRAINING SET")
print("=" * 80)

winner_idx = []
loser_idx = []

groups = data.groupby("system_slot").groups

for _, idx in tqdm(groups.items(), total=len(groups)):

    slot = data.loc[idx]

    slot = slot.sort_values("allocated_prbs", ascending=False)

    indices = slot.index.to_numpy()
    prbs = slot["allocated_prbs"].to_numpy()

    n = len(indices)

    for i in range(n):


        #All pairs
        for j in range(i + 1, n):

            if prbs[i] == prbs[j]:
                continue

            winner_idx.append(indices[i])
            loser_idx.append(indices[j])


winner_idx = np.array(winner_idx, dtype=np.int64)
loser_idx = np.array(loser_idx, dtype=np.int64)

FULL_PAIR_BASELINE = 2_658_699  # From the all-pairs experiment

print(f"Ranking pairs : {len(winner_idx):,}")
print(f"Winner indices: {winner_idx.shape}")
print(f"Loser indices : {loser_idx.shape}")
print(f"Pairs per slot: {len(winner_idx)/data['system_slot'].nunique():.2f}")
print(f"Pair reduction: {(1 - len(winner_idx)/FULL_PAIR_BASELINE)*100:.1f}%")

# ============================================================
# TORCH
# ============================================================

states = torch.tensor(X, dtype=torch.float32)

# ============================================================
# MODEL
# ============================================================

class PriorityNet(nn.Module):

    def __init__(self):

        super().__init__()

        self.net = nn.Sequential(

            nn.Linear(STATE_SIZE,128),
            nn.ReLU(),

            nn.Linear(128,128),
            nn.ReLU(),

            nn.Linear(128,1)
        )

    def forward(self,x):

        return self.net(x).squeeze(1)

model = PriorityNet()

optimizer = optim.AdamW(
    model.parameters(),
    lr=5e-4,
    weight_decay=1e-4
)
scheduler = optim.lr_scheduler.ReduceLROnPlateau(
    optimizer,
    mode="min",
    factor=0.5,
    patience=3
)

MARGIN = 0.05



# ============================================================
# PAIRWISE RANKING TRAINING
# ============================================================

print("\n" + "=" * 80)
print("PAIRWISE RANKING TRAINING")
print("=" * 80)

for epoch in range(EPOCHS):

    perm = torch.randperm(len(winner_idx))

    epoch_loss = 0.0
    batches = 0

    for i in range(0, len(winner_idx), BATCH_SIZE):

        batch = perm[i:i+BATCH_SIZE]

        w = torch.tensor(
            winner_idx[batch],
            dtype=torch.long
        )

        l = torch.tensor(
            loser_idx[batch],
            dtype=torch.long
        )

        winner_states = states[w]
        loser_states = states[l]

        winner_scores = model(winner_states)
        loser_scores = model(loser_states)

        loss = torch.relu(
            MARGIN -
            (winner_scores - loser_scores)
        ).mean()

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        epoch_loss += loss.item()
        batches += 1

    mean_loss = epoch_loss / batches
    scheduler.step(mean_loss)

    print(
        f"Epoch {epoch + 1:02d}/{EPOCHS} | "
        f"Ranking Loss: {mean_loss:.6f} | "
        f"LR: {optimizer.param_groups[0]['lr']:.1e}"
    )

torch.save(model.state_dict(), MODEL_FILE)

print("\nModel saved:")
print(MODEL_FILE)

# ============================================================
# PREDICT SCORES
# ============================================================

model.eval()

with torch.no_grad():

    data["priority_score"] = model(states).numpy()

# ============================================================
# SLOT-LEVEL ALLOCATION
# ============================================================


# ============================================================
# FAST SLOT-LEVEL ALLOCATION
# ============================================================

# Work on a single copy
pred_df = data.copy()

pred_df["pred_scheduled"] = 0
pred_df["pred_prbs"] = 0

print("\nEvaluating slot allocations...")

for _, idx in tqdm(
    pred_df.groupby("system_slot").groups.items(),
    total=pred_df["system_slot"].nunique()
):

    # indices belonging to this slot
    slot_idx = np.array(list(idx))

    # rank UEs by predicted priority (highest first)
    order = slot_idx[np.argsort(
        pred_df.loc[slot_idx, "priority_score"].to_numpy()
    )[::-1]]

    remaining = MAX_PRBS

    for i in order:

        need = pred_df.at[i, "allocated_prbs"]

        if remaining <= 0:
            break

        grant = min(need, remaining)

        pred_df.at[i, "pred_prbs"] = grant

        if grant > 0:
            pred_df.at[i, "pred_scheduled"] = 1

        remaining -= grant


# ============================================================
# SLOT EVALUATION
# ============================================================

print("\n" + "=" * 80)
print("SLOT LEVEL EVALUATION")
print("=" * 80)

conf = pd.crosstab(
    pred_df["scheduled"],
    pred_df["pred_scheduled"],
    rownames=["Actual"],
    colnames=["Predicted"]
)

print(conf)

accuracy = (
    pred_df["scheduled"] ==
    pred_df["pred_scheduled"]
).mean()

print(f"\nAccuracy: {accuracy:.4f}")

# ============================================================
# TOP-K OVERLAP
# ============================================================

overlaps = []

for slot, group in pred_df.groupby("system_slot"):

    actual = set(
        group[group["scheduled"]==1]["ue_id"]
    )

    predicted = set(
        group[group["pred_scheduled"]==1]["ue_id"]
    )

    if len(actual)==0:
        continue

    overlaps.append(
        len(actual & predicted) / len(actual)
    )

print(f"Average Top-K overlap: {np.mean(overlaps):.4f}")

print("\n" + "=" * 80)
print("THROUGHPUT RECOVERY")
print("=" * 80)

# Bytes recovered by selecting the same UEs
pred_df["pred_bytes"] = np.where(
    pred_df["pred_scheduled"] == 1,
    pred_df["allocated_bytes"],
    0
)

slot_stats = (
    pred_df.groupby("system_slot")
    .agg(
        actual_bytes=("allocated_bytes", "sum"),
        predicted_bytes=("pred_bytes", "sum"),
        actual_prbs=("allocated_prbs", "sum"),
        predicted_prbs=("pred_prbs", "sum"),
    )
)

slot_stats["throughput_recovery"] = (
    slot_stats["predicted_bytes"] /
    slot_stats["actual_bytes"].replace(0, np.nan)
)

slot_stats["prb_utilization"] = (
    slot_stats["predicted_prbs"] / MAX_PRBS
)

print(f"Average throughput recovery: {slot_stats['throughput_recovery'].mean():.3f}")
print(f"Average PRB utilization     : {slot_stats['prb_utilization'].mean():.3f}")



rank_corr = []

for _, group in pred_df.groupby("system_slot"):

    if len(group) < 2:
        continue

    actual_rank = group["allocated_prbs"].rank(
        method="dense",
        ascending=False
    )

    pred_rank = group["priority_score"].rank(
        method="dense",
        ascending=False
    )

    # Skip constant rankings
    if actual_rank.nunique() < 2 or pred_rank.nunique() < 2:
        continue

    corr, _ = spearmanr(actual_rank, pred_rank)

    if not np.isnan(corr):
        rank_corr.append(corr)

print(f"Average Spearman correlation: {np.mean(rank_corr):.3f}")
print(f"Median Spearman correlation : {np.median(rank_corr):.3f}")
print(f"Evaluated slots             : {len(rank_corr):,}")


# ============================================================
# CQI ANALYSIS
# ============================================================

pred_df["cqi_bucket"] = pd.cut(
    pred_df["reported_cqi"],
    bins=[0,3,6,9,12,15],
    labels=["1-3","4-6","7-9","10-12","13-15"]
)

bucket = (
    pred_df.groupby("cqi_bucket")
    .agg(
        samples=("ue_id","size"),
        predicted_rate=("pred_scheduled","mean"),
        actual_rate=("scheduled","mean"),
        mean_score=("priority_score","mean")
    )
)

bucket["predicted_rate"] *=100
bucket["actual_rate"] *=100

print("\n" + "=" * 80)
print("CQI BUCKET ANALYSIS")
print("=" * 80)

print(bucket.round(2).to_string())

print("\n" + "=" * 80)
print("PRIORITY SCORE DISTRIBUTION")
print("=" * 80)

score_stats = (
    pred_df.groupby("scheduled")["priority_score"]
    .describe()[["mean","std","25%","50%","75%"]]
)

print(score_stats.round(4))