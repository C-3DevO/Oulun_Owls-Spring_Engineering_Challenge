import torch
import torch.nn as nn
import numpy as np
import pandas as pd

STATE_SIZE = 5
NUM_ACTIONS = 5

MODEL_FILE = "cql_scheduler.pth"
HEADER_FILE = "cql_scheduler_weights.h"

# ============================================================
# EXPORTING
# ============================================================


class CQLNet(nn.Module):
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

model = CQLNet()
model.load_state_dict(torch.load(MODEL_FILE, map_location="cpu"))
model.eval()

layers = [m for m in model.net if isinstance(m, nn.Linear)]

with open(HEADER_FILE, "w") as f:
    f.write("#pragma once\n\n")

    for i, layer in enumerate(layers):
        w = layer.weight.detach().numpy()
        b = layer.bias.detach().numpy()

        rows, cols = w.shape

        f.write(f"static const float W{i}[{rows}][{cols}] = {{\n")
        for row in w:
            values = ", ".join(f"{x:.8f}f" for x in row)
            f.write(f"    {{{values}}},\n")
        f.write("};\n\n")

        values = ", ".join(f"{x:.8f}f" for x in b)
        f.write(f"static const float B{i}[{len(b)}] = {{{values}}};\n\n")

print(f"Exported {HEADER_FILE}")


# ============================================================
# VERIFYING THE EXPORTED MODEL
# ============================================================


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

model = CQLNet()
model.load_state_dict(torch.load("cql_scheduler.pth", map_location="cpu"))
model.eval()


df = pd.read_csv("DQN_clean.csv")

row = df.iloc[0]

x = np.array([[
    row["reported_cqi"] / 15,
    np.log1p(row["buffer"]) / 16.2,
    np.log1p(row["avg_rate"]) / 7.3,
    np.log1p(row["estimated_rate"]) / 8.7,
    np.log1p(row["pf_metric"]) / 5.5
]], dtype=np.float32)

print("Expected action:", row.get("action", "N/A"))
print("Expected priority:", row["dqn_priority"])

with torch.no_grad():
    q = model(torch.tensor(x))
    probs = torch.softmax(q, dim=1)
    priority = (probs * torch.arange(NUM_ACTIONS)).sum(dim=1)/(NUM_ACTIONS-1)

print("Input:", x)
print("Q-values:", q.numpy())
print("Softmax:", probs.numpy())
print("Action:", q.argmax(1).item())
print("Priority:", priority.item())