import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.stats import spearmanr

MODEL = "priority_ranker_rr_qos.pth"
CSV = "DQN_scheduler_log.csv"

STATE_SIZE = 5

# -------------------------------------------------------
# Model
# -------------------------------------------------------

class PriorityRanker(nn.Module):
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
        return self.net(x).squeeze(-1)

# -------------------------------------------------------
# Load model
# -------------------------------------------------------

model = PriorityRanker()
model.load_state_dict(torch.load(MODEL, map_location="cpu"))
model.eval()

# -------------------------------------------------------
# Load replay data
# -------------------------------------------------------

df = pd.read_csv(CSV)

replay = (
    df.sort_values(["system_slot","ue_id"])
      .groupby(["system_slot","ue_id"], as_index=False)
      .last()
)


# Expert ranking based on actual PRB allocation
replay["true_rank"] = (
    replay.groupby("system_slot")["allocated_prbs"]
          .rank(method="first", ascending=False)
)
# -------------------------------------------------------
# State preprocessing
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

# Same normalization used during training
X[:,0] /= 15
X[:,1] /= 16.2
X[:,2] /= 7.3
X[:,3] /= 8.7
X[:,4] /= 5.5

# -------------------------------------------------------
# Inference
# -------------------------------------------------------

with torch.no_grad():
    replay["pred_score"] = model(torch.tensor(X)).numpy()

replay["pred_rank"] = (
    replay.groupby("system_slot")["pred_score"]
          .rank(method="first", ascending=False)
)

# -------------------------------------------------------
# Offline evaluation metrics
# -------------------------------------------------------

# Top-1 Recovery
top1 = (
    replay.loc[replay.true_rank==1]
          .merge(
              replay.loc[replay.pred_rank==1],
              on="system_slot",
              suffixes=("_true","_pred")
          )
)

top1_recovery = (top1.ue_id_true == top1.ue_id_pred).mean()

# Spearman Correlation
corrs = []
for _, g in replay.groupby("system_slot"):
    c = spearmanr(g.true_rank, g.pred_rank).correlation
    if not np.isnan(c):
        corrs.append(c)

# Scheduled Precision
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

# Average Reward
reward_recovery = (
    replay.sort_values(["system_slot","pred_rank"])
          .groupby("system_slot")
          .first()
          .reward.mean()
)

# Average PRBs
prb_recovery = (
    replay.sort_values(["system_slot","pred_rank"])
          .groupby("system_slot")
          .first()
          .allocated_prbs.mean()
)

# -------------------------------------------------------
# Results
# -------------------------------------------------------

print("="*60)
print("SLR POLICY EVALUATION")
print("="*60)
print(f"Slots                 : {replay.system_slot.nunique():,}")
print(f"Top-1 recovery        : {top1_recovery:.3f}")
print(f"Mean Spearman         : {np.mean(corrs):.3f}")
print(f"Median Spearman       : {np.median(corrs):.3f}")
print(f"Scheduled precision   : {scheduled_precision:.3f}")
print(f"Avg reward (Top-1 UE) : {reward_recovery:.3f}")
print(f"Avg PRBs (Top-1 UE)   : {prb_recovery:.1f}")