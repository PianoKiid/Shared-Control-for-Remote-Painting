"""Dependency-free diagonal Gaussian mixture model."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


LOG_2PI = float(np.log(2.0 * np.pi))


def logsumexp(values: np.ndarray, axis: int | None = None) -> np.ndarray:
    maximum = np.max(values, axis=axis, keepdims=True)
    safe = np.where(np.isfinite(maximum), maximum, 0.0)
    result = safe + np.log(np.sum(np.exp(values - safe), axis=axis, keepdims=True))
    if axis is None:
        return np.asarray(result.squeeze())
    return np.squeeze(result, axis=axis)


@dataclass
class DiagonalGMM:
    weights: np.ndarray
    means: np.ndarray
    variances: np.ndarray
    converged: bool = True
    iterations: int = 0
    average_log_likelihood: float = float("nan")

    @property
    def components(self) -> int:
        return int(len(self.weights))

    @property
    def dimension(self) -> int:
        return int(self.means.shape[1])

    def component_log_prob(self, features: np.ndarray) -> np.ndarray:
        values = np.atleast_2d(np.asarray(features, dtype=np.float64))
        difference = values[:, None, :] - self.means[None, :, :]
        gaussian = -0.5 * (
            self.dimension * LOG_2PI
            + np.sum(np.log(self.variances), axis=1)[None, :]
            + np.sum(difference * difference / self.variances[None, :, :], axis=2)
        )
        return gaussian + np.log(np.maximum(self.weights, 1e-300))[None, :]

    def score_samples(self, features: np.ndarray) -> np.ndarray:
        return logsumexp(self.component_log_prob(features), axis=1)


def kmeans_plus_plus(features: np.ndarray, components: int, rng: np.random.Generator) -> np.ndarray:
    n = len(features)
    means = np.empty((components, features.shape[1]), dtype=np.float64)
    means[0] = features[int(rng.integers(n))]
    closest = np.sum((features - means[0]) ** 2, axis=1)
    for component in range(1, components):
        total = float(np.sum(closest))
        if total <= 0 or not np.isfinite(total):
            means[component] = features[int(rng.integers(n))]
        else:
            means[component] = features[int(rng.choice(n, p=closest / total))]
        closest = np.minimum(closest, np.sum((features - means[component]) ** 2, axis=1))
    return means


def fit_diagonal_gmm(
    features: np.ndarray,
    components: int,
    seed: int,
    maximum_iterations: int = 100,
    tolerance: float = 1e-4,
    covariance_floor: float = 1e-3,
) -> DiagonalGMM:
    values = np.asarray(features, dtype=np.float64)
    if values.ndim != 2 or not len(values):
        raise ValueError("GMM training features must be a non-empty matrix")
    components = int(min(max(1, components), len(values)))
    rng = np.random.default_rng(seed)
    means = kmeans_plus_plus(values, components, rng)
    global_variance = np.maximum(np.var(values, axis=0), covariance_floor)
    variances = np.repeat(global_variance[None, :], components, axis=0)
    weights = np.full(components, 1.0 / components, dtype=np.float64)
    previous = -np.inf
    converged = False

    for iteration in range(1, maximum_iterations + 1):
        model = DiagonalGMM(weights, means, variances)
        component_log = model.component_log_prob(values)
        normalization = logsumexp(component_log, axis=1)
        average = float(np.mean(normalization))
        responsibilities = np.exp(component_log - normalization[:, None])
        effective = responsibilities.sum(axis=0)

        for component in range(components):
            if effective[component] < 1e-6:
                means[component] = values[int(rng.integers(len(values)))]
                variances[component] = global_variance
                effective[component] = 1.0
                continue
            weight = responsibilities[:, component]
            means[component] = (weight @ values) / effective[component]
            difference = values - means[component]
            variances[component] = np.maximum(
                (weight @ (difference * difference)) / effective[component],
                covariance_floor,
            )
        weights = np.maximum(effective, 1e-12)
        weights /= weights.sum()
        if np.isfinite(previous) and abs(average - previous) <= tolerance * (1.0 + abs(previous)):
            converged = True
            break
        previous = average

    final = DiagonalGMM(weights, means, variances)
    final.converged = converged
    final.iterations = iteration
    final.average_log_likelihood = float(np.mean(final.score_samples(values)))
    return final
