import copy
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import random

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

LOG_FILE = "DQN_clean.csv"

Q_MODEL = "iql_q.pth"
V_MODEL = "iql_v.pth"
ACTOR_MODEL = "iql_actor.pth"

EXPECTILE = 0.8
BETA = 3.0

STATE_SIZE = 5
NUM_ACTIONS = 5

BATCH_SIZE = 4096
EPOCHS = 30


LR = 3e-4
GAMMA = 0.99
TAU = 0.005


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

pair_i = torch.tensor(pair_i, dtype=torch.long)
pair_j = torch.tensor(pair_j, dtype=torch.long)

print(f"Pairwise comparisons: {len(pair_i):,}")


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
# TENSOR CREATION
# ============================================================

states = torch.tensor(X, dtype=torch.float32)
next_states = torch.tensor(X_next, dtype=torch.float32)
actions = torch.tensor(replay["action"].values, dtype=torch.long)
rewards = torch.tensor(replay["reward"].values, dtype=torch.float32)

# ============================================================
# REPLAY SUMMARY
# ============================================================

replay["cqi_bucket"] = pd.cut(
    replay["reported_cqi"],
    bins=[0,3,6,9,12,15],
    labels=["1-3","4-6","7-9","10-12","13-15"]
)

print("\n" + "="*60)
print("REPLAY SUMMARY")
print("="*60)

print(f"Samples      : {len(replay):,}")
print(f"Slots        : {replay['system_slot'].nunique():,}")
print(f"State shape  : {tuple(states.shape)}")
print(f"Reward mean  : {replay['reward'].mean():.3f}")
print(f"Zero rewards : {(replay['reward']==0).mean()*100:.1f}%")

print("\nAction rewards")
print(
    replay.groupby("action")["reward"]
          .mean()
          .round(3)
          .to_string()
)

print("\nReward vs CQI")
print(
    replay.groupby("cqi_bucket")
          .agg(
              reward=("reward","mean"),
              bytes=("allocated_bytes","mean")
          )
          .round(3)
          .to_string()
)


#IQL Network definition
class QNet(nn.Module):

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


class ValueNet(nn.Module):

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


class ActorNet(nn.Module):

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


#IQL Network definition
q_net = QNet()
target_q = copy.deepcopy(q_net)

for p in target_q.parameters():
    p.requires_grad = False

v_net = ValueNet()
actor = ActorNet()

q_opt = optim.AdamW(
    q_net.parameters(),
    lr=LR,
    weight_decay=1e-4
)

v_opt = optim.AdamW(
    v_net.parameters(),
    lr=LR
)

actor_opt = optim.AdamW(
    actor.parameters(),
    lr=LR
)



# ============================================================
# TRAINING
# ============================================================

print("\nStarting IQL training...\n")

for epoch in range(EPOCHS):

    perm = torch.randperm(states.size(0))

    epoch_loss = 0
    batches = 0

    for i in range(0, states.size(0), BATCH_SIZE):

        idx = perm[i:i+BATCH_SIZE]

        s = states[idx]
        ns = next_states[idx]
        a = actions[idx]
        r = rewards[idx]

        # ------------------------
        # Q update
        # ------------------------

        q = q_net(s)
        chosen_q = q.gather(1, a.unsqueeze(1)).squeeze(1)

        with torch.no_grad():
            target = r + GAMMA * target_q(ns).max(1)[0]

        q_loss = F.mse_loss(chosen_q, target)

        q_opt.zero_grad()
        q_loss.backward()
        q_opt.step()

        # ------------------------
        # Value update (Expectile)
        # ------------------------

        v = v_net(s)

        advantage = chosen_q.detach() - v

        weight = torch.where(
            advantage > 0,
            EXPECTILE,
            1 - EXPECTILE
        )

        v_loss = (weight * advantage.pow(2)).mean()

        v_opt.zero_grad()
        v_loss.backward()
        v_opt.step()

        # ------------------------
        # Actor update (Pairwise IQL)
        # ------------------------

        logits = actor(s)

        # Convert logits to a continuous priority score in [0,1]
        probs = torch.softmax(logits, dim=1)

        priority = (
                           probs * torch.arange(
                       NUM_ACTIONS,
                       device=logits.device,
                       dtype=torch.float32
                   )
                   ).sum(dim=1) / (NUM_ACTIONS - 1)

        # Build pairwise loss for pairs present in this batch
        mask = torch.isin(pair_i, idx) & torch.isin(pair_j, idx)

        if mask.any():

            batch_i = pair_i[mask]
            batch_j = pair_j[mask]

            mapping = torch.full(
                (len(replay),),
                -1,
                dtype=torch.long,
                device=logits.device
            )

            mapping[idx] = torch.arange(
                len(idx),
                device=logits.device
            )

            bi = mapping[batch_i]
            bj = mapping[batch_j]

            score_i = priority[bi]
            score_j = priority[bj]

            # IQL advantages from the Value network
            with torch.no_grad():

                q_values = q_net(s)
                q_taken = q_values.gather(1, a.unsqueeze(1)).squeeze(1)
                v_values = v_net(s)

                batch_advantage = q_taken - v_values
                pair_advantage = (batch_advantage[bi] + batch_advantage[bj]) / 2

                pair_weight = torch.exp(BETA * pair_advantage).clamp(max=20.0)

            margin_loss = F.margin_ranking_loss(
                score_i,
                score_j,
                torch.ones_like(score_i),
                margin=0.2,
                reduction="none"
            )

            actor_loss = (pair_weight * margin_loss).mean()

        else:

            actor_loss = torch.tensor(0.0, device=logits.device)

        actor_opt.zero_grad()
        actor_loss.backward()
        actor_opt.step()

        epoch_loss += (
            q_loss.item()
            + v_loss.item()
            + actor_loss.item()
        )

        batches += 1

    # Soft target update
    for p, tp in zip(
        q_net.parameters(),
        target_q.parameters()
    ):
        tp.data.copy_(
            TAU * p.data + (1 - TAU) * tp.data
        )


    if epoch == 0 or (epoch + 1) % 5 == 0:
        print(
            f"Epoch {epoch+1:02d}/{EPOCHS} | "
            f"Loss: {epoch_loss/batches:.4f}"
        )

# ============================================================
# SAVE MODELS
# ============================================================

torch.save(q_net.state_dict(), Q_MODEL)
torch.save(v_net.state_dict(), V_MODEL)
torch.save(actor.state_dict(), ACTOR_MODEL)

print("Saved:", Q_MODEL)
print("Saved:", V_MODEL)
print("Saved:", ACTOR_MODEL)


# ============================================================
# IQL POLICY EVALUATION
# ============================================================

from scipy.stats import spearmanr

q_net.eval()
v_net.eval()
actor.eval()

with torch.no_grad():
    logits = actor(states)
    probs = torch.softmax(logits, dim=1)
    pred_action = logits.argmax(1).numpy()

    priority_score = (
        probs *
        torch.arange(NUM_ACTIONS, dtype=torch.float32)
    ).sum(dim=1)/(NUM_ACTIONS-1)

pred_df = replay.copy()
pred_df["pred_action"] = pred_action
pred_df["priority_score"] = priority_score.numpy()

# Predicted rank (1 = highest)
pred_df["pred_rank"] = NUM_ACTIONS - pred_df["pred_action"]
pred_df["true_rank"] = pred_df["slot_rank"]

# ============================================================
# Ranking metrics
# ============================================================

corr = []
top1 = []

for _, g in pred_df.groupby("system_slot"):

    if g["pred_rank"].nunique() > 1:
        c = spearmanr(g["true_rank"], g["pred_rank"]).correlation
        corr.append(c)

    top1.append(
        g.loc[g["true_rank"].idxmin(), "ue_id"] ==
        g.loc[g["pred_action"].idxmax(), "ue_id"]
    )

# ============================================================
# Deployment replay
# ============================================================

MAX_PRBS = 51

pred_df["pred_scheduled"] = False
pred_df["pred_prbs"] = 0

for _, idx in pred_df.groupby("system_slot").groups.items():

    order = sorted(
        idx,
        key=lambda i: pred_df.at[i, "priority_score"],
        reverse=True
    )

    remaining = MAX_PRBS

    for i in order:

        need = pred_df.at[i, "allocated_prbs"]

        if remaining <= 0:
            break

        grant = min(need, remaining)

        pred_df.at[i, "pred_prbs"] = grant
        pred_df.at[i, "pred_scheduled"] = grant > 0

        remaining -= grant

scheduled_precision = (
    pred_df["scheduled"] ==
    pred_df["pred_scheduled"]
).mean()

top_reward = (
    pred_df.sort_values(
        ["system_slot","priority_score"],
        ascending=[True,False]
    )
    .groupby("system_slot")
    .first()["reward"]
    .mean()
)

top_prbs = (
    pred_df.sort_values(
        ["system_slot","priority_score"],
        ascending=[True,False]
    )
    .groupby("system_slot")
    .first()["allocated_prbs"]
    .mean()
)

print("\n" + "="*60)
print("IQL POLICY EVALUATION")
print("="*60)

print(f"Slots                 : {pred_df['system_slot'].nunique():,}")
print(f"Top-1 recovery        : {np.mean(top1):.3f}")
print(f"Mean Spearman         : {np.mean(corr):.3f}")
print(f"Median Spearman       : {np.median(corr):.3f}")
print(f"Scheduled precision   : {scheduled_precision:.3f}")
print(f"Avg reward (Top-1 UE) : {top_reward:.3f}")
print(f"Avg PRBs (Top-1 UE)   : {top_prbs:.1f}")
