import torch
import torch.nn as nn
import numpy as np

MODEL_FILE = "priority_ranker_rr_qos.pth"
HEADER_FILE = "priority_ranker_weights.h"

STATE_SIZE = 5

class PriorityNet(nn.Module):
    def __init__(self):
        super().__init__()

        self.net = nn.Sequential(
            nn.Linear(STATE_SIZE, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, 1)
        )

    def forward(self, x):
        return self.net(x)

model = PriorityNet()
model.load_state_dict(torch.load(MODEL_FILE, map_location="cpu"))
model.eval()

layers = [m for m in model.net if isinstance(m, nn.Linear)]

with open(HEADER_FILE, "w") as f:

    f.write("#pragma once\n\n")

    for i, layer in enumerate(layers):

        w = layer.weight.detach().numpy()
        b = layer.bias.detach().numpy()

        rows, cols = w.shape

        f.write(
            f"static const float W{i}[{rows}][{cols}] = {{\n"
        )

        for row in w:
            values = ", ".join(f"{x:.8f}f" for x in row)
            f.write(f"{{{values}}},\n")

        f.write("};\n\n")

        values = ", ".join(f"{x:.8f}f" for x in b)

        f.write(
            f"static const float B{i}[{len(b)}] = "
            f"{{{values}}};\n\n"
        )

print(f"Exported {HEADER_FILE}")