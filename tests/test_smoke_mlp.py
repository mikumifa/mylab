from __future__ import annotations

import math
import random
import unittest


def relu(value: float) -> float:
    return value if value > 0.0 else 0.0


def relu_grad(value: float) -> float:
    return 1.0 if value > 0.0 else 0.0


def softmax(logits: list[float]) -> list[float]:
    peak = max(logits)
    exps = [math.exp(value - peak) for value in logits]
    total = sum(exps)
    return [value / total for value in exps]


class TinyMLP:
    def __init__(
        self, input_dim: int, hidden_dim: int, output_dim: int, seed: int
    ) -> None:
        rng = random.Random(seed)
        self.w1 = [
            [rng.uniform(-0.5, 0.5) for _ in range(hidden_dim)]
            for _ in range(input_dim)
        ]
        self.b1 = [0.0 for _ in range(hidden_dim)]
        self.w2 = [
            [rng.uniform(-0.5, 0.5) for _ in range(output_dim)]
            for _ in range(hidden_dim)
        ]
        self.b2 = [0.0 for _ in range(output_dim)]

    def forward(
        self, features: list[float]
    ) -> tuple[list[float], list[float], list[float]]:
        hidden_linear = []
        hidden = []
        for hidden_index in range(len(self.b1)):
            value = self.b1[hidden_index]
            for input_index, feature in enumerate(features):
                value += feature * self.w1[input_index][hidden_index]
            hidden_linear.append(value)
            hidden.append(relu(value))

        logits = []
        for output_index in range(len(self.b2)):
            value = self.b2[output_index]
            for hidden_index, hidden_value in enumerate(hidden):
                value += hidden_value * self.w2[hidden_index][output_index]
            logits.append(value)
        return hidden_linear, hidden, softmax(logits)

    def train_step(self, features: list[float], label: int, lr: float) -> float:
        hidden_linear, hidden, probs = self.forward(features)
        loss = -math.log(max(probs[label], 1e-12))

        grad_logits = probs[:]
        grad_logits[label] -= 1.0

        grad_w2 = [
            [
                hidden[hidden_index] * grad_logits[output_index]
                for output_index in range(len(self.b2))
            ]
            for hidden_index in range(len(self.b1))
        ]
        grad_b2 = grad_logits[:]

        grad_hidden = []
        for hidden_index in range(len(self.b1)):
            total = 0.0
            for output_index in range(len(self.b2)):
                total += self.w2[hidden_index][output_index] * grad_logits[output_index]
            grad_hidden.append(total * relu_grad(hidden_linear[hidden_index]))

        grad_w1 = [
            [
                features[input_index] * grad_hidden[hidden_index]
                for hidden_index in range(len(self.b1))
            ]
            for input_index in range(len(features))
        ]
        grad_b1 = grad_hidden[:]

        for hidden_index in range(len(self.b1)):
            for output_index in range(len(self.b2)):
                self.w2[hidden_index][output_index] -= (
                    lr * grad_w2[hidden_index][output_index]
                )
        for output_index in range(len(self.b2)):
            self.b2[output_index] -= lr * grad_b2[output_index]

        for input_index in range(len(features)):
            for hidden_index in range(len(self.b1)):
                self.w1[input_index][hidden_index] -= (
                    lr * grad_w1[input_index][hidden_index]
                )
        for hidden_index in range(len(self.b1)):
            self.b1[hidden_index] -= lr * grad_b1[hidden_index]

        return loss

    def predict(self, features: list[float]) -> int:
        _, _, probs = self.forward(features)
        return max(range(len(probs)), key=lambda index: probs[index])


def make_dataset() -> list[tuple[list[float], int]]:
    rng = random.Random(7)
    samples: list[tuple[list[float], int]] = []
    for _ in range(48):
        x1 = rng.uniform(-2.0, -0.2)
        x2 = rng.uniform(-2.0, -0.2)
        samples.append(([x1, x2], 0))
    for _ in range(48):
        x1 = rng.uniform(0.2, 2.0)
        x2 = rng.uniform(0.2, 2.0)
        samples.append(([x1, x2], 1))
    rng.shuffle(samples)
    return samples


class SmokeMLPTest(unittest.TestCase):
    def test_tiny_mlp_learns_simple_classification(self) -> None:
        dataset = make_dataset()
        model = TinyMLP(input_dim=2, hidden_dim=6, output_dim=2, seed=11)
        initial_loss = sum(
            model.train_step(features, label, 0.0) for features, label in dataset
        ) / len(dataset)

        losses = []
        for _ in range(60):
            epoch_loss = 0.0
            for features, label in dataset:
                epoch_loss += model.train_step(features, label, lr=0.05)
            losses.append(epoch_loss / len(dataset))

        accuracy = sum(
            1 for features, label in dataset if model.predict(features) == label
        ) / len(dataset)

        self.assertLess(losses[-1], initial_loss * 0.35)
        self.assertGreater(accuracy, 0.95)


if __name__ == "__main__":
    unittest.main()
