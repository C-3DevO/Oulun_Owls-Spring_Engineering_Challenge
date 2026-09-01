import copy
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

LOG_FILE = "DQN_clean.csv"

MODEL_FILE = "cql_scheduler.pth"

STATE_SIZE = 5
NUM_ACTIONS = 5

BATCH_SIZE = 4096
EPOCHS = 30
RANK_WEIGHT = 1.0

LR = 5e-4
GAMMA = 0.99
TAU = 0.005
ALPHA = 1.0

#Load Replay Buffer
data = pd.read_csv(LOG_FILE)
print(f"Replay samples: {len(data):,}")

#Building State
data["buffer_log"] = np.log1p(data["buffer"])
data["avg_rate_log"] = np.log1p(data["avg_rate"])
data["estimated_rate_log"] = np.log1p(data["estimated_rate"])
data["pf_metric_log"] = np.log1p(data["pf_metric"])

# ============================================================
# ACTIONS FROM UNIQUE UE RANKING
# ============================================================

# Keep one scheduling decision per UE per slot.
slot_policy = (
    data.sort_values(["system_slot", "ue_id"])
        .groupby(["system_slot", "ue_id"], as_index=False)
        .last()
)

# Rank UEs inside each slot.
slot_policy["slot_rank"] = (
    slot_policy.groupby("system_slot")["dqn_priority"]
        .rank(method="first", ascending=False)
        .astype(int)
)

# Convert rank -> action.
# Rank:   1  2  3  4  5
# Action: 4  3  2  1  0
slot_policy["action"] = (
    NUM_ACTIONS - slot_policy["slot_rank"]
).clip(lower=0, upper=NUM_ACTIONS-1).astype(int)



print("\nUnique UE decisions")
print(
    slot_policy[
        ["system_slot","ue_id","dqn_priority","slot_rank","action"]
    ]
    .sort_values(["system_slot","slot_rank"])
    .head(15)
)

print("\nAction distribution")
print(slot_policy["action"].value_counts().sort_index())

# Sanity check: why are there many replay rows per slot?
rows_per_slot = data.groupby("system_slot").size()

print("\nReplay rows per slot")
print(rows_per_slot.describe().round(2))

print("\nFirst replay rows of slot 0")
print(
    data[data["system_slot"] == 0][
        ["system_slot","ue_id","scheduled",
         "allocated_prbs","dqn_priority"]
    ].head(40)
)

# ============================================================
# BUILD UNIQUE RL REPLAY (ONE DECISION PER UE PER SLOT)
# ============================================================

# One RL transition per (system_slot, UE)
replay = slot_policy.copy()

# Make indices contiguous BEFORE building pairs
replay = replay.reset_index(drop=True)

# Keep only complete 5-UE slots
slot_counts = replay.groupby("system_slot")["ue_id"].nunique()

good_slots = slot_counts[slot_counts == NUM_ACTIONS].index

replay = replay[
    replay["system_slot"].isin(good_slots)
].reset_index(drop=True)

print(f"Complete slots kept : {len(good_slots):,}")
print(f"Replay samples       : {len(replay):,}")


# Build next-state PF
replay["next_pf_metric"] = (
    replay["next_estimated_rate"] /
    np.maximum(replay["next_avg_rate"],1.0)
).clip(0,100)

# Log features
replay["buffer_log"] = np.log1p(replay["buffer"])
replay["avg_rate_log"] = np.log1p(replay["avg_rate"])
replay["estimated_rate_log"] = np.log1p(replay["estimated_rate"])
replay["pf_metric_log"] = np.log1p(replay["pf_metric"])

replay["next_buffer_log"] = np.log1p(replay["next_buffer"])
replay["next_avg_rate_log"] = np.log1p(replay["next_avg_rate"])
replay["next_estimated_rate_log"] = np.log1p(replay["next_estimated_rate"])
replay["next_pf_metric_log"] = np.log1p(replay["next_pf_metric"])

# ============================================================
# PAIRWISE RANKING DATASET
# ============================================================

pair_i = []
pair_j = []

for _, g in replay.groupby("system_slot"):

    g = g.sort_values("slot_rank")

    idx = g.index.to_list()

    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            pair_i.append(idx[a])
            pair_j.append(idx[b])

pair_i = np.array(pair_i)
pair_j = np.array(pair_j)

expected_pairs = replay["system_slot"].nunique() * 10

print(f"Pairwise comparisons: {len(pair_i):,}")
print(f"Expected comparisons : {expected_pairs:,}")

assert len(pair_i) == expected_pairs
assert len(pair_j) == expected_pairs


#Building x and x_next from reolay
X = replay[
    ["reported_cqi","buffer_log","avg_rate_log",
     "estimated_rate_log","pf_metric_log"]
].to_numpy(dtype=np.float32)

X_next = replay[
    ["next_reported_cqi","next_buffer_log",
     "next_avg_rate_log","next_estimated_rate_log",
     "next_pf_metric_log"]
].to_numpy(dtype=np.float32)

# Same normalization
X[:,0] /= 15
X[:,1] /= 16.2
X[:,2] /= 7.3
X[:,3] /= 8.7
X[:,4] /= 5.5

X_next[:,0] /= 15
X_next[:,1] /= 16.2
X_next[:,2] /= 7.3
X_next[:,3] /= 8.7
X_next[:,4] /= 5.5


# ============================================================
# Tensor creation
# ============================================================


pair_i = torch.tensor(pair_i, dtype=torch.long)
pair_j = torch.tensor(pair_j, dtype=torch.long)

states = torch.tensor(X,dtype=torch.float32)
next_states = torch.tensor(X_next,dtype=torch.float32)

actions = torch.tensor(
    replay["action"].values,
    dtype=torch.long
)

rewards = torch.tensor(
    replay["reward"].values,
    dtype=torch.float32
)

# ============================================================
# Tensor summary
# ============================================================

print("\nReplay tensors")
print(f"States      : {states.shape}")
print(f"Next states : {next_states.shape}")
print(f"Actions     : {actions.shape}")
print(f"Rewards     : {rewards.shape}")

# ============================================================
# REPLAY BUFFER ANALYSIS
# ============================================================

print("\n" + "="*80)
print("REPLAY BUFFER SUMMARY")
print("="*80)

print(f"Samples : {len(replay):,}")
print(f"Slots   : {replay['system_slot'].nunique():,}")
print(f"UEs     : {replay['ue_id'].nunique()}")


print("\nReward statistics")
print(replay["reward"].describe().round(4))

print("\n" + "="*80)
print("ZERO-REWARD ANALYSIS")
print("="*80)

zero_reward = replay[replay["reward"] == 0]

print(f"Zero-reward transitions : {len(zero_reward):,}")
print(f"Percentage               : {100*len(zero_reward)/len(replay):.1f}%")

print("\nScheduled among zero-reward:")
print(zero_reward["scheduled"].value_counts())

print("\nZero-reward CQI distribution:")
print(
    zero_reward.groupby("reported_cqi")
               .size()
               .head(15)
)

print("\nAction distribution")
print(replay["action"].value_counts().sort_index())


print("\n" + "="*80)
print("ACTION CHARACTERISTICS")
print("="*80)

action_stats = (
    replay.groupby("action")
    .agg(
        samples=("action","size"),
        mean_reward=("reward","mean"),
        mean_cqi=("reported_cqi","mean"),
        mean_buffer=("buffer","mean"),
        mean_pf=("pf_metric","mean"),
        mean_priority=("dqn_priority","mean")
    )
)

print(action_stats.round(3).to_string())

# ============================================================
# CQI VS ACTION
# ============================================================

replay["cqi_bucket"] = pd.cut(
    replay["reported_cqi"],
    bins=[0,3,6,9,12,15],
    labels=["1-3","4-6","7-9","10-12","13-15"]
)

cqi_action = pd.crosstab(
    replay["cqi_bucket"],
    replay["action"],
    normalize="index"
) * 100

print("\n" + "="*80)
print("CQI VS ACTION")
print("="*80)

print(cqi_action.round(1).to_string())

# ============================================================
# REWARD VS CQI
# ============================================================

reward_cqi = (
    replay.groupby("cqi_bucket")
    .agg(
        mean_reward=("reward","mean"),
        mean_bytes=("allocated_bytes","mean"),
        samples=("reward","size")
    )
)

print("\n" + "="*80)
print("REWARD VS CQI")
print("="*80)

print(reward_cqi.round(3).to_string())


# ============================================================
# SLOT ACTION DIVERSITY
# ============================================================

slot_diversity = (
    replay.groupby("system_slot")["action"]
    .nunique()
)

print("\n" + "="*80)
print("PER-SLOT ACTION DIVERSITY")
print("="*80)

print(slot_diversity.describe().round(2))


#CQL Network definition
class CQLNet(nn.Module):

    def __init__(self):

        super().__init__()

        self.net = nn.Sequential(

            nn.Linear(STATE_SIZE,128),
            nn.ReLU(),

            nn.Linear(128,128),
            nn.ReLU(),

            nn.Linear(128,NUM_ACTIONS)
        )

    def forward(self,x):

        return self.net(x)

#Network definition
model = CQLNet()
target_net = copy.deepcopy(model)

optimizer = optim.AdamW(
    model.parameters(),
    lr=LR,
    weight_decay=1e-4
)

#Training
print("\nStarting CQL training...\n")

for epoch in range(EPOCHS):

    perm = torch.randperm(states.size(0))

    epoch_loss = 0
    batches = 0

    for i in range(0,states.size(0),BATCH_SIZE):

        idx = perm[i:i+BATCH_SIZE]

        s = states[idx]
        ns = next_states[idx]
        a = actions[idx]
        r = rewards[idx]

        q = model(s)

        chosen_q = q.gather(
            1,
            a.unsqueeze(1)
        ).squeeze(1)

        # Bellman target
        with torch.no_grad():
            next_q = target_net(ns)
            target = r + GAMMA * next_q.max(1)[0]

        bellman_loss = F.mse_loss(chosen_q, target)

        # Conservative CQL loss
        conservative_loss = (
                torch.logsumexp(q, dim=1)
                - chosen_q
        ).mean()

        # ============================================================
        # PAIRWISE RANKING LOSS
        # ============================================================

        # Which pairwise comparisons are fully inside this batch?
        mask = torch.isin(pair_i, idx) & torch.isin(pair_j, idx)

        if mask.any():

            # Global replay indices
            batch_i = pair_i[mask]
            batch_j = pair_j[mask]

            # Map global replay index -> local batch position
            mapping = torch.full(
                (len(replay),),
                -1,
                dtype=torch.long
            )
            mapping[idx] = torch.arange(len(idx))

            bi = mapping[batch_i]
            bj = mapping[batch_j]

            # Convert logits into a continuous priority score
            probs = torch.softmax(q, dim=1)

            priority = (
                               probs * torch.arange(NUM_ACTIONS, device=q.device, dtype=torch.float32)
                       ).sum(dim=1) / (NUM_ACTIONS - 1)

            score_i = priority[bi]
            score_j = priority[bj]

            rank_loss = F.margin_ranking_loss(
                score_i,
                score_j,
                torch.ones_like(score_i),
                margin=0.2
            )

        else:
            rank_loss = torch.tensor(0.0, device=q.device)

        # Final loss
        loss = (
                bellman_loss
                + ALPHA * conservative_loss
                + RANK_WEIGHT * rank_loss
        )

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        epoch_loss += loss.item()
        batches += 1

    for p,tp in zip(
        model.parameters(),
        target_net.parameters()
    ):
        tp.data.copy_(
            TAU*p.data + (1-TAU)*tp.data
        )

    if epoch == 0 or (epoch + 1) % 5 == 0:
        print(f"Epoch {epoch + 1:02d}/{EPOCHS} | Loss: {epoch_loss / batches:.4f}")

#Saving the model
torch.save(
    model.state_dict(),
    MODEL_FILE
)

print("Saved:",MODEL_FILE)


# ============================================================
# Q-VALUE ANALYSIS
# ============================================================

model.eval()

with torch.no_grad():
    q = model(states)

q_df = pd.DataFrame(
    q.numpy(),
    columns=[f"Q{i}" for i in range(NUM_ACTIONS)]
)

print("\n" + "="*80)
print("Q-VALUE DISTRIBUTION")
print("="*80)

print(q_df.describe().round(3))

# ============================================================
#Preferred action distribution
# ============================================================
pred_action = q.argmax(1).numpy()

pred_stats = pd.Series(pred_action).value_counts().sort_index()

print("\n" + "="*80)
print("PREFERRED ACTION DISTRIBUTION")
print("="*80)

print(pred_stats)

print("\nPercentages")
print((pred_stats/len(pred_action)*100).round(2))


# ============================================================
# PREDICTED ACTION VS CQI
# ============================================================

pred_df = replay.copy()
pred_df["pred_action"] = pred_action

bucket = (
    pred_df.groupby("cqi_bucket")
    .agg(
        predicted_action=("pred_action","mean"),
        reward=("reward","mean"),
        cqi=("reported_cqi","mean")
    )
)

print("\n" + "="*80)
print("PREDICTED ACTION VS CQI")
print("="*80)

print(bucket.round(3).to_string())

# ============================================================
# RANK RECOVERY ANALYSIS
# ============================================================

from scipy.stats import spearmanr

print("\n" + "="*80)
print("RANK RECOVERY ANALYSIS")
print("="*80)

# Ground-truth rank (1=highest ... 5=lowest)
pred_df["true_rank"] = pred_df["slot_rank"]

# Convert predicted action back to predicted rank
# Action: 4→rank1, 3→rank2, ..., 0→rank5
pred_df["pred_rank"] = NUM_ACTIONS - pred_df["pred_action"]

# Rank error statistics
rank_error = pred_df["pred_rank"] - pred_df["true_rank"]

print("Rank error statistics")
print(rank_error.describe().round(3))

# Spearman correlation for each slot
corr = []

for _, g in pred_df.groupby("system_slot"):

    if len(g) > 1:
        c = spearmanr(g["true_rank"], g["pred_rank"]).correlation
        if not np.isnan(c):
            corr.append(c)

print(f"\nMean Spearman correlation : {np.mean(corr):.4f}")
print(f"Median Spearman           : {np.median(corr):.4f}")
print(f"Perfect-order slots       : {(np.array(corr)==1).mean()*100:.1f}%")



print("\nAction diversity per slot")

action_div = pred_df.groupby("system_slot")["pred_action"].nunique()

print(action_div.describe())

print("\nSlots with only one predicted action:")
print((action_div==1).sum())


print("\n" + "="*80)
print("TOP-1 RECOVERY")
print("="*80)

top1 = []

for _, g in pred_df.groupby("system_slot"):

    true_top = g.loc[g["true_rank"].idxmin(), "ue_id"]
    pred_top = g.loc[g["pred_action"].idxmax(), "ue_id"]

    top1.append(true_top == pred_top)

print(f"Top-1 recovery: {np.mean(top1):.4f}")

# ============================================================
# DEPLOYMENT PRIORITY EVALUATION
# ============================================================

with torch.no_grad():
    q = model(states)

# Chosen action
pred_action = q.argmax(1)

# Softmax over Q-values
probs = torch.softmax(q, dim=1)

# Expected priority in [0,1]
priority_score = (
    probs * torch.arange(NUM_ACTIONS, dtype=torch.float32)
).sum(dim=1) / (NUM_ACTIONS - 1)

pred_df = replay.copy()
pred_df["priority_score"] = priority_score.numpy()
pred_df["pred_action"] = pred_action.numpy()


# ============================================================
# REPLAY SCHEDULER
# ============================================================

MAX_PRBS = 51

pred_df["pred_scheduled"] = 0
pred_df["pred_prbs"] = 0

for slot, idx in pred_df.groupby("system_slot").groups.items():

    slot_idx = np.array(list(idx))

    order = slot_idx[
        np.argsort(
            pred_df.loc[slot_idx, "priority_score"].to_numpy()
        )[::-1]
    ]

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
# REPLAY EVALUATION
# ============================================================

print("\n" + "="*80)
print("REPLAY EVALUATION")
print("="*80)

conf = pd.crosstab(
    pred_df["scheduled"],
    pred_df["pred_scheduled"],
    rownames=["Actual"],
    colnames=["Predicted"]
)

print(conf)

#Accuracy
accuracy = (
    pred_df["scheduled"] ==
    pred_df["pred_scheduled"]
).mean()

print(f"\nAccuracy: {accuracy:.4f}")

# Top K overlap
overlaps = []
for _, group in pred_df.groupby("system_slot"):

    actual = set(group[group["scheduled"]==1]["ue_id"])
    predicted = set(group[group["pred_scheduled"]==1]["ue_id"])

    if actual:
        overlaps.append(
            len(actual & predicted) / len(actual)
        )

print(f"Average Top-K overlap: {np.mean(overlaps):.4f}")


#Throughput recovery
pred_df["pred_bytes"] = np.where(
    pred_df["pred_scheduled"] == 1,
    pred_df["allocated_bytes"],
    0
)

slot_stats = (
    pred_df.groupby("system_slot")
    .agg(
        actual_bytes=("allocated_bytes","sum"),
        predicted_bytes=("pred_bytes","sum"),
        predicted_prbs=("pred_prbs","sum")
    )
)

slot_stats["throughput_recovery"] = (
    slot_stats["predicted_bytes"] /
    slot_stats["actual_bytes"].replace(0,np.nan)
)

slot_stats["prb_utilization"] = (
    slot_stats["predicted_prbs"] / MAX_PRBS
)

print(f"Average throughput recovery: {slot_stats['throughput_recovery'].mean():.3f}")
print(f"Average PRB utilization     : {slot_stats['prb_utilization'].mean():.3f}")

#FInal Diagnostic
print(pd.crosstab(
    replay["action"],
    pred_df["pred_action"],
    rownames=["True"],
    colnames=["Predicted"]
))