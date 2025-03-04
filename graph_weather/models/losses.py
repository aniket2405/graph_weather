"""Weather loss functions"""

import numpy as np
import torch


class NormalizedMSELoss(torch.nn.Module):
    """Loss function described in the paper"""

    def __init__(
        self, feature_variance: list, lat_lons: list, device="cpu", normalize: bool = False
    ):
        """
        Normalized MSE Loss as described in the paper

        This re-scales each physical variable such that it has unit-variance in the 3 hour temporal
        difference. E.g. for temperature data, divide every one at all pressure levels by
        sigma_t_3hr, where sigma^2_T,3hr is the variance of the 3 hour change in temperature,
         averaged across space (lat/lon + pressure levels) and time (100 random temporal frames).

         Additionally weights by the cos(lat) of the feature

         cos and sin should be in radians

        Args:
            feature_variance: Variance for each of the physical features
            lat_lons: List of lat/lon pairs, used to generate weighting
            device: checks for device whether it supports gpu or not
            normalize: option for normalize
        """
        # TODO Rescale by nominal static air density at each pressure level, could be 1/pressure level or something similar
        super().__init__()
        self.feature_variance = torch.tensor(feature_variance)
        assert not torch.isnan(self.feature_variance).any()
        weights = []
        for lat, lon in lat_lons:
            weights.append(np.cos(lat * np.pi / 180.0))
        self.weights = torch.tensor(weights, dtype=torch.float)
        self.normalize = normalize
        assert not torch.isnan(self.weights).any()

    def forward(self, pred: torch.Tensor, target: torch.Tensor):
        """
        Calculate the loss

        Rescales both predictions and target, so assumes neither are already normalized
        Additionally weights by the cos(lat) of the set of features

        Args:
            pred: Prediction tensor
            target: Target tensor

        Returns:
            MSE loss on the variance-normalized values
        """
        self.feature_variance = self.feature_variance.to(pred.device)
        self.weights = self.weights.to(pred.device)
        print(pred.shape)
        print(target.shape)
        print(self.weights.shape)

        out = (pred - target) ** 2
        print(out.shape)
        if self.normalize:
            out = out / self.feature_variance

        assert not torch.isnan(out).any()
        # Mean of the physical variables
        out = out.mean(-1)
        print(out.shape)
        # Weight by the latitude, as that changes, so does the size of the pixel
        out = out * self.weights.expand_as(out)
        assert not torch.isnan(out).any()
        return out.mean()
