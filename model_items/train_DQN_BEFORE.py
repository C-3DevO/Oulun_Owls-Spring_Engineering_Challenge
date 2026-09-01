import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

# ============================================================
# CONFIG
# ============================================================

RR_FILE = "RR_clean.csv"
QOS_FILE = "QOS_clean.csv"

MODEL_FILE = "dqn_rr_qos.pth"
WEIGHTS_FILE = "dqn_rr_qos_weights.h"

STATE_SIZE = 5
ACTION_SIZE = 9

BATCH_SIZE = 2048
EPOCHS = 30
LR = 0.001
GAMMA = 0.99

REWARD_SCALE = 5889.0

# ============================================================
# STATE FEATURES
# ============================================================

STATE_FEATURES = [
    "reported_cqi",
    "buffer_log",
    "avg_rate_log",
    "estimated_rate_log",
    "pf_metric_log",
]

NEXT_STATE_FEATURES = [
    "next_reported_cqi",
    "next_buffer_log",
    "next_avg_rate_log",
    "next_estimated_rate_log",
    "next_pf_metric_log",
]

# ============================================================
# LOAD DATA
# ============================================================

rr = pd.read_csv(RR_FILE)
qos = pd.read_csv(QOS_FILE)

print("=" * 80)
print("RR + QoS DQN TRAINING")
print("=" * 80)

print(f"RR rows  : {len(rr):,}")
print(f"QoS rows : {len(qos):,}")

# ============================================================
# CREATE NEXT LOG FEATURES
# ============================================================

def prepare_dataset(data):

    data = data.copy()

    # Current-state transformations
    data["buffer_log"] = np.log1p(data["buffer"])
    data["avg_rate_log"] = np.log1p(data["avg_rate"])
    data["estimated_rate_log"] = np.log1p(
        data["estimated_rate"]
    )
    data["pf_metric_log"] = np.log1p(
        data["pf_metric"]
    )

    # Next-state transformations
    data["next_buffer_log"] = np.log1p(
        data["next_buffer"]
    )
    data["next_avg_rate_log"] = np.log1p(
        data["next_avg_rate"]
    )
    data["next_estimated_rate_log"] = np.log1p(
        data["next_estimated_rate"]
    )

    # --------------------------------------------------------
    # IMPORTANT:
    # There is NO next_pf_metric in the cleaned logs.
    #
    # We therefore use the current PF metric as the best
    # available representation for the next-state PF feature.
    # --------------------------------------------------------

    data["next_pf_metric_log"] = data["pf_metric_log"]

    return data


rr = prepare_dataset(rr)
qos = prepare_dataset(qos)

# ============================================================
# REMOVE FINAL TRANSITION
# ============================================================

rr = rr.iloc[:-1].copy()
qos = qos.iloc[:-1].copy()

print("\nRR transitions  :", f"{len(rr):,}")
print("QoS transitions :", f"{len(qos):,}")

# ============================================================
# COMBINE DATASETS
# ============================================================

data = pd.concat(
    [rr, qos],
    ignore_index=True
)

print("Total transitions :", f"{len(data):,}")

# ============================================================
# VALIDATE REQUIRED COLUMNS
# ============================================================

required_columns = (
    STATE_FEATURES
    + NEXT_STATE_FEATURES
    + [
        "allocated_prbs",
        "allocated_bytes",
    ]
)

missing = [
    c for c in required_columns
    if c not in data.columns
]

if missing:
    raise ValueError(
        f"Missing required columns: {missing}"
    )

# ============================================================
# ACTION REPRESENTATION
# ============================================================

# We define the DQN action from PRB allocation.
#
# 9 actions:
#
# 0 -> no allocation
# 1 -> very small allocation
# ...
# 8 -> largest allocation
#
# The allocation is quantized into 9 bins.

PRB_MAX = data["allocated_prbs"].max()

print("\nMaximum allocated PRBs :", PRB_MAX)

# np.digitize gives bins 0...8
bins = np.linspace(
    0,
    PRB_MAX + 1,
    ACTION_SIZE + 1
)

data["action"] = np.digitize(
    data["allocated_prbs"],
    bins[1:-1],
    right=False
)

# Safety
data["action"] = data["action"].clip(
    0,
    ACTION_SIZE - 1
).astype(np.int64)

print("\nAction distribution:")
print(
    data["action"]
    .value_counts()
    .sort_index()
)

# ============================================================
# ACTION → PRB → REWARD ANALYSIS
# ============================================================

print("\n" + "=" * 80)
print("ACTION → PRB → REWARD ANALYSIS")
print("=" * 80)

action_analysis = (
    data.groupby("action")
    .agg(
        samples=("action", "size"),
        mean_prbs=("allocated_prbs", "mean"),
        median_prbs=("allocated_prbs", "median"),
        mean_bytes=("allocated_bytes", "mean"),
        median_bytes=("allocated_bytes", "median"),
        max_bytes=("allocated_bytes", "max"),
    )
)

print(action_analysis.to_string())

print("\n" + "=" * 80)
print("ACTION → SCHEDULING RATE")
print("=" * 80)

action_sched = (
    data.groupby("action")["allocated_prbs"]
    .apply(lambda x: (x > 0).mean() * 100)
)

print(action_sched)

# ============================================================
# STATE
# ============================================================

X = data[
    STATE_FEATURES
].to_numpy(
    dtype=np.float32
)

X_next = data[
    NEXT_STATE_FEATURES
].to_numpy(
    dtype=np.float32
)

actions = data[
    "action"
].to_numpy(
    dtype=np.int64
)

# ============================================================
# REWARD
# ============================================================

rewards = data[
    "allocated_bytes"
].to_numpy(
    dtype=np.float32
)

# Normalize reward to approximately [0,1]
rewards = rewards / REWARD_SCALE

# ============================================================
# STATE NORMALIZATION
# ============================================================

X[:, 0] /= 15.0
X[:, 1] /= 16.2
X[:, 2] /= 7.3
X[:, 3] /= 8.7
X[:, 4] /= 5.5

X_next[:, 0] /= 15.0
X_next[:, 1] /= 16.2
X_next[:, 2] /= 7.3
X_next[:, 3] /= 8.7
X_next[:, 4] /= 5.5

# ============================================================
# NUMERICAL SAFETY
# ============================================================

print("\nState NaN :", np.isnan(X).sum())
print("State Inf :", np.isinf(X).sum())

print("Next NaN  :", np.isnan(X_next).sum())
print("Next Inf  :", np.isinf(X_next).sum())

print("Reward NaN:", np.isnan(rewards).sum())
print("Reward Inf:", np.isinf(rewards).sum())

# ============================================================
# TORCH TENSORS
# ============================================================

states = torch.tensor(
    X,
    dtype=torch.float32
)

next_states = torch.tensor(
    X_next,
    dtype=torch.float32
)

actions = torch.tensor(
    actions,
    dtype=torch.long
)

rewards = torch.tensor(
    rewards,
    dtype=torch.float32
)

print("\n" + "=" * 80)
print("TRAINING DATA")
print("=" * 80)

print("States      :", states.shape)
print("Next states :", next_states.shape)
print("Actions     :", actions.shape)
print("Rewards     :", rewards.shape)

print(
    f"Reward min  : {rewards.min().item():.4f}"
)

print(
    f"Reward mean : {rewards.mean().item():.4f}"
)

print(
    f"Reward max  : {rewards.max().item():.4f}"
)

# ============================================================
# DQN MODEL
# ============================================================

class DQN(nn.Module):

    def __init__(self):

        super().__init__()

        self.net = nn.Sequential(

            nn.Linear(
                STATE_SIZE,
                128
            ),

            nn.ReLU(),

            nn.Linear(
                128,
                128
            ),

            nn.ReLU(),

            nn.Linear(
                128,
                ACTION_SIZE
            )
        )

    def forward(self, x):

        return self.net(x)


model = DQN()

target_model = DQN()

target_model.load_state_dict(
    model.state_dict()
)

# ============================================================
# TRAINING
# ============================================================

optimizer = optim.Adam(
    model.parameters(),
    lr=LR
)

loss_fn = nn.MSELoss()

print("\n" + "=" * 80)
print("TRAINING")
print("=" * 80)

for epoch in range(EPOCHS):

    permutation = torch.randperm(
        states.size(0)
    )

    epoch_loss = 0.0
    batches = 0

    for i in range(
        0,
        states.size(0),
        BATCH_SIZE
    ):

        idx = permutation[
            i:i + BATCH_SIZE
        ]

        s = states[idx]
        s_next = next_states[idx]
        a = actions[idx]
        r = rewards[idx]

        # ----------------------------------------------------
        # Current Q values
        # ----------------------------------------------------

        q_values = model(s)

        q_sa = q_values.gather(
            1,
            a.unsqueeze(1)
        ).squeeze(1)

        # ----------------------------------------------------
        # Target Q values
        # ----------------------------------------------------

        with torch.no_grad():

            q_next = target_model(
                s_next
            )

            max_q_next = q_next.max(
                dim=1
            ).values

            target = (
                r
                + GAMMA * max_q_next
            )

        # ----------------------------------------------------
        # Loss
        # ----------------------------------------------------

        loss = loss_fn(
            q_sa,
            target
        )

        optimizer.zero_grad()

        loss.backward()

        optimizer.step()

        epoch_loss += loss.item()

        batches += 1

    # Update target network
    target_model.load_state_dict(
        model.state_dict()
    )

    mean_loss = (
        epoch_loss / batches
    )

    print(
        f"Epoch {epoch + 1:02d}/{EPOCHS} "
        f"| Loss: {mean_loss:.6f}"
    )

# ============================================================
# SAVE MODEL
# ============================================================

torch.save(
    model.state_dict(),
    MODEL_FILE
)

print("\nModel saved:")
print(MODEL_FILE)

# ============================================================
# QUICK CHECK
# ============================================================

model.eval()

with torch.no_grad():

    sample = states[:20]

    q_values = model(
        sample
    )

    predicted_actions = torch.argmax(
        q_values,
        dim=1
    )

print("\nSample predicted actions:")
print(
    predicted_actions.numpy()
)

print("\nTraining complete.")

# ============================================================
# LOAD MODEL
# ============================================================

model = DQN()
model.load_state_dict(
    torch.load(
        "dqn_rr_qos.pth",
        map_location="cpu"
    )
)

model.eval()

# ============================================================
# Q-VALUE ANALYSIS
# ============================================================

with torch.no_grad():

    q_values = model(states)

print("=" * 80)
print("DQN Q-VALUE ANALYSIS")
print("=" * 80)

print("\nMean Q-value for each action:")

mean_q = q_values.mean(dim=0)

for action in range(ACTION_SIZE):

    print(
        f"Action {action}: "
        f"{mean_q[action].item():.6f}"
    )



# ============================================================
# Q-VALUE STATISTICS
# ============================================================

print("\nQ-value statistics:")

for action in range(ACTION_SIZE):

    q = q_values[:, action]

    print(
        f"Action {action}: "
        f"min={q.min().item():.4f}, "
        f"mean={q.mean().item():.4f}, "
        f"max={q.max().item():.4f}"
    )


# ============================================================
# PREDICTED ACTION DISTRIBUTION
# ============================================================

with torch.no_grad():
    predicted = torch.argmax(q_values, dim=1)

pred_counts = (
    pd.Series(predicted.numpy())
    .value_counts()
    .sort_index()
)

print("\nPredicted action distribution:")
print(pred_counts)

print("\nPredicted action percentages:")
print((pred_counts / len(predicted) * 100).round(2))

# ============================================================
# STATE VS PREDICTED ACTION
# ============================================================

pred_df = data.copy()
pred_df["pred_action"] = predicted.numpy()

print("\n" + "=" * 80)
print("STATE VS PREDICTED ACTION")
print("=" * 80)

analysis = (
    pred_df.groupby("pred_action")
    .agg(
        samples=("pred_action", "size"),
        mean_cqi=("reported_cqi", "mean"),
        mean_buffer=("buffer", "mean"),
        mean_pf=("pf_metric", "mean"),
        mean_prbs=("allocated_prbs", "mean"),
        mean_reward=("allocated_bytes", "mean"),
    )
)

print(analysis.to_string())