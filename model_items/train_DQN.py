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

STATE_SIZE = 5
ACTION_SIZE = 2

BATCH_SIZE = 2048
EPOCHS = 30
LR = 0.001
GAMMA = 0.99

MAX_BYTES = 5889.0

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

MAX_PF = max(rr["pf_metric"].max(), qos["pf_metric"].max())

print("=" * 80)
print("RR + QoS DQN TRAINING")
print("=" * 80)

print(f"RR rows  : {len(rr):,}")
print(f"QoS rows : {len(qos):,}")

# ============================================================
# FEATURE PREPARATION
# ============================================================

def prepare_dataset(df):

    df = df.copy()

    df["buffer_log"] = np.log1p(df["buffer"])
    df["avg_rate_log"] = np.log1p(df["avg_rate"])
    df["estimated_rate_log"] = np.log1p(df["estimated_rate"])
    df["pf_metric_log"] = np.log1p(df["pf_metric"])

    df["next_buffer_log"] = np.log1p(df["next_buffer"])
    df["next_avg_rate_log"] = np.log1p(df["next_avg_rate"])
    df["next_estimated_rate_log"] = np.log1p(df["next_estimated_rate"])

    # No next_pf_metric exists in the logs.
    df["next_pf_metric_log"] = df["pf_metric_log"]

    return df


rr = prepare_dataset(rr)
qos = prepare_dataset(qos)

# Remove final transition from each dataset

rr = rr.iloc[:-1].copy()
qos = qos.iloc[:-1].copy()

print(f"\nRR transitions  : {len(rr):,}")
print(f"QoS transitions : {len(qos):,}")

# ============================================================
# COMBINE RR + QoS
# ============================================================

data = pd.concat([rr, qos], ignore_index=True)

print(f"Total transitions : {len(data):,}")

# ============================================================
# ACTION (Binary Scheduling Decision)
# ============================================================

data["action"] = data["scheduled"].astype(np.int64)

print("\nAction distribution:")
print(data["action"].value_counts().sort_index())

# ============================================================
# REWARD
# ============================================================


# ============================================================
# REWARD
# ============================================================

throughput_reward = data["allocated_bytes"] / MAX_BYTES

MAX_PF_LOG = np.log1p(MAX_PF)
fairness_reward = np.log1p(data["pf_metric"]) / MAX_PF_LOG

cost_penalty = data["allocated_prbs"] / 51.0

reward = (
    0.6 * throughput_reward +
    0.4 * fairness_reward -
    0.2 * cost_penalty
)

# Penalize scheduled UEs that consumed resources but carried almost no data
waste_mask = (
    (data["scheduled"] == 1) &
    (data["allocated_bytes"] < 100)
)

reward = np.where(waste_mask, reward - 0.3, reward)

reward = np.clip(reward, -1.0, 1.0)

data["reward_train"] = reward


print("\n" + "=" * 80)
print("SCHEDULED VS NOT SCHEDULED")
print("=" * 80)

reward_analysis = (
    data.groupby("action")
    .agg(
        samples=("action", "size"),
        mean_prbs=("allocated_prbs", "mean"),
        mean_bytes=("allocated_bytes", "mean"),
        mean_pf=("pf_metric", "mean"),
        mean_reward=("reward_train", "mean"),
        low_throughput=("allocated_bytes", lambda x: (x < 100).mean() * 100),
    )
)

print(reward_analysis.to_string())

# ============================================================
# BUILD STATES
# ============================================================

X = data[STATE_FEATURES].to_numpy(dtype=np.float32)
X_next = data[NEXT_STATE_FEATURES].to_numpy(dtype=np.float32)

actions = data["action"].to_numpy(dtype=np.int64)
rewards = data["reward_train"].to_numpy(dtype=np.float32)

# ============================================================
# NORMALIZATION
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
# NUMERICAL CHECK
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

states = torch.tensor(X, dtype=torch.float32)
next_states = torch.tensor(X_next, dtype=torch.float32)
actions = torch.tensor(actions, dtype=torch.long)
rewards = torch.tensor(rewards, dtype=torch.float32)

print("\n" + "=" * 80)
print("TRAINING DATA")
print("=" * 80)

print("States      :", states.shape)
print("Next states :", next_states.shape)
print("Actions     :", actions.shape)
print("Rewards     :", rewards.shape)

print(f"Reward min  : {rewards.min():.4f}")
print(f"Reward mean : {rewards.mean():.4f}")
print(f"Reward max  : {rewards.max():.4f}")

# ============================================================
# DQN
# ============================================================

class DQN(nn.Module):

    def __init__(self):
        super().__init__()

        self.net = nn.Sequential(
            nn.Linear(STATE_SIZE, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, ACTION_SIZE),
        )

    def forward(self, x):
        return self.net(x)


model = DQN()
target_model = DQN()

target_model.load_state_dict(model.state_dict())

optimizer = optim.Adam(model.parameters(), lr=LR)
loss_fn = nn.MSELoss()

# ============================================================
# TRAINING
# ============================================================

print("\n" + "=" * 80)
print("TRAINING")
print("=" * 80)

for epoch in range(EPOCHS):

    permutation = torch.randperm(states.size(0))

    epoch_loss = 0.0
    batches = 0

    for i in range(0, states.size(0), BATCH_SIZE):

        idx = permutation[i:i+BATCH_SIZE]

        s = states[idx]
        s_next = next_states[idx]
        a = actions[idx]
        r = rewards[idx]

        q_values = model(s)
        q_sa = q_values.gather(1, a.unsqueeze(1)).squeeze(1)

        with torch.no_grad():
            q_next = target_model(s_next)
            target = r + GAMMA * q_next.max(dim=1).values

        loss = loss_fn(q_sa, target)

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        epoch_loss += loss.item()
        batches += 1

    target_model.load_state_dict(model.state_dict())

    print(
        f"Epoch {epoch+1:02d}/{EPOCHS} | "
        f"Loss: {epoch_loss/batches:.6f}"
    )

# ============================================================
# SAVE
# ============================================================

torch.save(model.state_dict(), MODEL_FILE)

print("\nModel saved:")
print(MODEL_FILE)

# ============================================================
# PREDICTIONS
# ============================================================

model.eval()

with torch.no_grad():

    q_values = model(states)
    predicted = torch.argmax(q_values, dim=1)

print("\nTraining complete.")

# ============================================================
# CONFUSION MATRIX
# ============================================================

print("\n" + "=" * 80)
print("CONFUSION MATRIX")
print("=" * 80)

conf = pd.crosstab(
    data["scheduled"],
    predicted.numpy(),
    rownames=["Actual"],
    colnames=["Predicted"]
)

print(conf)

accuracy = (predicted.numpy() == data["scheduled"]).mean()

print(f"\nAccuracy: {accuracy:.4f}")


tp = ((data["scheduled"] == 1) & (predicted.numpy() == 1)).sum()
fp = ((data["scheduled"] == 0) & (predicted.numpy() == 1)).sum()
fn = ((data["scheduled"] == 1) & (predicted.numpy() == 0)).sum()

precision = tp / (tp + fp)
recall = tp / (tp + fn)

print(f"Precision: {precision:.4f}")
print(f"Recall   : {recall:.4f}")

# ============================================================
# Q VALUE ANALYSIS
# ============================================================

print("\n" + "=" * 80)
print("DQN Q-VALUE ANALYSIS")
print("=" * 80)

mean_q = q_values.mean(dim=0)

for action in range(ACTION_SIZE):

    print(
        f"Action {action}: "
        f"{mean_q[action].item():.6f}"
    )

print("\nQ-value statistics:")

for action in range(ACTION_SIZE):

    q = q_values[:, action]

    print(
        f"Action {action}: "
        f"min={q.min():.4f}, "
        f"mean={q.mean():.4f}, "
        f"max={q.max():.4f}"
    )

# ============================================================
# PREDICTION DISTRIBUTION
# ============================================================

pred_counts = (
    pd.Series(predicted.numpy())
    .value_counts()
    .sort_index()
)

print("\nPredicted scheduling decisions:")
print(pred_counts)

print("\nPredicted percentages:")
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
        mean_reward=("reward_train", "mean"),
    )
)

print(analysis.to_string())


# ============================================================
# CQI BUCKET ANALYSIS
# ============================================================

print("\n" + "=" * 80)
print("CQI BUCKET ANALYSIS")
print("=" * 80)

pred_df["cqi_bucket"] = pd.cut(
    pred_df["reported_cqi"],
    bins=[0, 3, 6, 9, 12, 15],
    labels=["1-3", "4-6", "7-9", "10-12", "13-15"]
)

bucket = (
    pred_df.groupby("cqi_bucket")
    .agg(
        samples=("pred_action", "size"),
        predicted_schedule_rate=("pred_action", "mean"),
        actual_schedule_rate=("scheduled", "mean"),
        mean_reward=("reward_train", "mean"),
        mean_prbs=("allocated_prbs", "mean")
    )
)

bucket["predicted_schedule_rate"] *= 100
bucket["actual_schedule_rate"] *= 100

print(bucket.round(2).to_string())
