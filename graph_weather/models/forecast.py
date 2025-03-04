"""Model for forecasting weather from NWP states"""

from typing import Optional

import einops
import torch
from huggingface_hub import PyTorchModelHubMixin

from graph_weather.models import Decoder, Encoder, Processor
from graph_weather.models.layers.constraint_layer import PhysicalConstraintLayer

class GraphWeatherForecaster(torch.nn.Module, PyTorchModelHubMixin):
    """Main weather prediction model from the paper with physical constraints"""

    def __init__(
        self,
        lat_lons: list,
        resolution: int = 2,
        feature_dim: int = 78,
        aux_dim: int = 24,
        output_dim: Optional[int] = None,
        node_dim: int = 256,
        edge_dim: int = 256,
        num_blocks: int = 9,
        hidden_dim_processor_node: int = 256,
        hidden_dim_processor_edge: int = 256,
        hidden_layers_processor_node: int = 2,
        hidden_layers_processor_edge: int = 2,
        hidden_dim_decoder: int = 128,
        hidden_layers_decoder: int = 2,
        norm_type: str = "LayerNorm",
        use_checkpointing: bool = False,
        # New constraint parameters
        constraint_type: str = "additive",  # "additive", "multiplicative", or "softmax"
        apply_constraints: bool = True,
    ):
        """
        Graph Weather Model based off https://arxiv.org/pdf/2202.07575.pdf

        Args:
            lat_lons: List of latitude and longitudes for the grid
            resolution: Resolution of the H3 grid, prefer even resolutions, as
                odd ones have octogons and heptagons as well
            feature_dim: Input feature size
            aux_dim: Number of non-NWP features (i.e. landsea mask, lat/lon, etc)
            output_dim: Optional, output feature size, useful if want only subset of variables in
            output
            node_dim: Node hidden dimension
            edge_dim: Edge hidden dimension
            num_blocks: Number of message passing blocks in the Processor
            hidden_dim_processor_node: Hidden dimension of the node processors
            hidden_dim_processor_edge: Hidden dimension of the edge processors
            hidden_layers_processor_node: Number of hidden layers in the node processors
            hidden_layers_processor_edge: Number of hidden layers in the edge processors
            hidden_dim_decoder:Number of hidden dimensions in the decoder
            hidden_layers_decoder: Number of layers in the decoder
            norm_type: Type of norm for the MLPs
                one of 'LayerNorm', 'GraphNorm', 'InstanceNorm', 'BatchNorm', 'MessageNorm', or None
            use_checkpointing: Use gradient checkpointing to reduce model memory
        """
        super().__init__()
        self.feature_dim = feature_dim
        self.apply_constraints = apply_constraints
        if output_dim is None:
            output_dim = self.feature_dim
        self.output_dim = output_dim

        # Compute the geographical grid shape from lat_lons.
        unique_lats = sorted(set(lat for lat, _ in lat_lons))
        unique_lons = sorted(set(lon for _, lon in lat_lons))
        self.grid_shape = (len(unique_lats), len(unique_lons))  # (H, W)    

        self.encoder = Encoder(
            lat_lons=lat_lons,
            resolution=resolution,
            input_dim=feature_dim + aux_dim,
            output_dim=node_dim,
            output_edge_dim=edge_dim,
            hidden_dim_processor_edge=hidden_dim_processor_edge,
            hidden_layers_processor_node=hidden_layers_processor_node,
            hidden_dim_processor_node=hidden_dim_processor_node,
            hidden_layers_processor_edge=hidden_layers_processor_edge,
            mlp_norm_type=norm_type,
            use_checkpointing=use_checkpointing,
        )
        self.processor = Processor(
            input_dim=node_dim,
            edge_dim=edge_dim,
            num_blocks=num_blocks,
            hidden_dim_processor_edge=hidden_dim_processor_edge,
            hidden_layers_processor_node=hidden_layers_processor_node,
            hidden_dim_processor_node=hidden_dim_processor_node,
            hidden_layers_processor_edge=hidden_layers_processor_edge,
            mlp_norm_type=norm_type,
        )
        self.decoder = Decoder(
            lat_lons=lat_lons,
            resolution=resolution,
            input_dim=node_dim,
            output_dim=output_dim,
            output_edge_dim=edge_dim,
            hidden_dim_processor_edge=hidden_dim_processor_edge,
            hidden_layers_processor_node=hidden_layers_processor_node,
            hidden_dim_processor_node=hidden_dim_processor_node,
            hidden_layers_processor_edge=hidden_layers_processor_edge,
            mlp_norm_type=norm_type,
            hidden_dim_decoder=hidden_dim_decoder,
            hidden_layers_decoder=hidden_layers_decoder,
            use_checkpointing=use_checkpointing,
        )

        # Add physical constraint layer
        self.constraint = PhysicalConstraintLayer(
            grid_shape=self.grid_shape,
            constraint_type=constraint_type)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        """
        Compute the new state of the forecast

        Args:
            features: The input features, aligned with the order of lat_lons_heights

        Returns:
            The next state in the forecast
        """
        x, edge_idx, edge_attr = self.encoder(features)
        x = self.processor(x, edge_idx, edge_attr)
        x = self.decoder(x, features[..., : self.feature_dim])
        # Here, assume decoder output x is a 4D tensor, e.g. [B, output_dim, H, W] where H and W are grid dimensions.

        # Convert graph output to grid format
        batch_size = x.shape[0]
        x = x.view(batch_size, self.output_dim, self.grid_shape[0], self.grid_shape[1])

        # Apply physical constraints to decoder output
        if self.apply_constraints:
            # Extract the low-res reference from the input.
            # (Original features has shape [B, num_nodes, feature_dim])
            lr = features[..., : self.feature_dim]   # shape: [B, num_nodes, feature_dim]
            # Convert from node format to grid format using the grid_shape computed in __init__
            lr = lr.permute(0, 2, 1)                    # becomes [B, feature_dim, num_nodes]

            lr = lr.view(batch_size, self.feature_dim, self.grid_shape[0], self.grid_shape[1])
            if lr.size(1) != x.size(1):
                lr = lr.repeat(1, x.size(1)//lr.size(1), 1, 1)
            x = self.constraint(x, lr)
        return x.view(batch_size, -1, self.output_dim)