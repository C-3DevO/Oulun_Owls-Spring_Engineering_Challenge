import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.stats import spearmanr

MODEL = "iql_actor.pth"
CSV = "DQN_IQL_scheduler_log.csv"

STATE_SIZE = 5
NUM_ACTIONS = 5


class ActorNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(STATE_SIZE, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, NUM_ACTIONS)
        )

    def forward(self, x):
        return self.net(x)


# -------------------------------------------------------
# Load model
# -------------------------------------------------------

model = ActorNet()
model.load_state_dict(torch.load(MODEL, map_location="cpu"))
model.eval()

# -------------------------------------------------------
# Load data
# -------------------------------------------------------

df = pd.read_csv(CSV)

replay = (
    df.sort_values(["system_slot", "ue_id"])
      .groupby(["system_slot", "ue_id"], as_index=False)
      .last()
)

replay["true_rank"] = (
    replay.groupby("system_slot")["dqn_priority"]
          .rank(method="first", ascending=False)
)

# -------------------------------------------------------
# Build normalized state
# -------------------------------------------------------

replay["buffer_log"] = np.log1p(replay["buffer"])
replay["avg_rate_log"] = np.log1p(replay["avg_rate"])
replay["estimated_rate_log"] = np.log1p(replay["estimated_rate"])
replay["pf_metric_log"] = np.log1p(replay["pf_metric"])

X = replay[
    ["reported_cqi",
     "buffer_log",
     "avg_rate_log",
     "estimated_rate_log",
     "pf_metric_log"]
].to_numpy(dtype=np.float32)

X[:, 0] /= 15
X[:, 1] /= 16.2
X[:, 2] /= 7.3
X[:, 3] /= 8.7
X[:, 4] /= 5.5

# -------------------------------------------------------
# Inference
# -------------------------------------------------------

with torch.no_grad():

    logits = model(torch.tensor(X))

    probs = torch.softmax(logits, dim=1)

    replay["pred_action"] = logits.argmax(1).numpy()

    replay["pred_score"] = (
        probs *
        torch.arange(NUM_ACTIONS, dtype=torch.float32)
    ).sum(dim=1).numpy() / (NUM_ACTIONS - 1)

replay["pred_rank"] = (
    replay.groupby("system_slot")["pred_score"]
          .rank(method="first", ascending=False)
)

# -------------------------------------------------------
# Metrics
# -------------------------------------------------------

# Top-1 recovery
top1 = (
    replay.loc[replay.true_rank == 1]
          .merge(
              replay.loc[replay.pred_rank == 1],
              on="system_slot",
              suffixes=("_true", "_pred")
          )
)

top1_recovery = (top1.ue_id_true == top1.ue_id_pred).mean()

# Spearman
corrs = []
for _, g in replay.groupby("system_slot"):
    c = spearmanr(g.true_rank, g.pred_rank).correlation
    if not np.isnan(c):
        corrs.append(c)

# Scheduled precision
scheduled_precision = (
    replay.groupby("system_slot")
          .apply(
              lambda g:
              g.sort_values("pred_rank")
               .head(g.scheduled.sum())
               .scheduled.mean()
          )
          .mean()
)

# Reward recovered
reward_recovery = (
    replay.sort_values(["system_slot", "pred_rank"])
          .groupby("system_slot")
          .first()
          .reward.mean()
)

# PRB recovered
prb_recovery = (
    replay.sort_values(["system_slot", "pred_rank"])
          .groupby("system_slot")
          .first()
          .allocated_prbs.mean()
)

print("=" * 60)
print("IQL POLICY EVALUATION")
print("=" * 60)
print(f"Slots                 : {replay.system_slot.nunique():,}")
print(f"Top-1 recovery        : {top1_recovery:.3f}")
print(f"Mean Spearman         : {np.mean(corrs):.3f}")
print(f"Median Spearman       : {np.median(corrs):.3f}")
print(f"Scheduled precision   : {scheduled_precision:.3f}")
print(f"Avg reward (Top-1 UE) : {reward_recovery:.3f}")
print(f"Avg PRBs (Top-1 UE)   : {prb_recovery:.1f}")