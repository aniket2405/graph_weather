import h3
import numpy as np
import torch

from graph_weather import GraphWeatherAssimilator, GraphWeatherForecaster
from graph_weather.models import (
    AssimilatorDecoder,
    AssimilatorEncoder,
    Decoder,
    Encoder,
    ImageMetaModel,
    MetaModel,
    Processor,
    WrapperImageModel,
    WrapperMetaModel,
)
from graph_weather.models.losses import NormalizedMSELoss


def test_encoder():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))
    model = Encoder(lat_lons).eval()

    features = torch.randn((2, len(lat_lons), 78))
    with torch.no_grad():
        x, edge_idx, edge_attr = model(features)
    assert x.size() == (5882 * 2, 256)
    assert edge_idx.size() == (2, 41162 * 2)


def test_encoder_uneven_grid():
    lat_lons = []
    for lat in range(-90, 90, 7):
        for lon in range(0, 180, 5):
            lat_lons.append((lat, lon))
        for lon in range(180, 360, 9):
            lat_lons.append((lat, lon))
    model = Encoder(lat_lons).eval()

    features = torch.randn((2, len(lat_lons), 78))
    with torch.no_grad():
        x, edge_idx, edge_attr = model(features)
    assert x.size() == (5882 * 2, 256)
    assert edge_idx.size() == (2, 41162 * 2)


def test_assimilation_encoder_uneven_grid():
    lat_lons = []
    for lat in range(-90, 90, 7):
        for lon in range(0, 180, 5):
            lat_lons.append((lat, lon, np.random.random(1)))
        for lon in range(180, 360, 9):
            lat_lons.append((lat, lon, np.random.random(1)))
    model = AssimilatorEncoder().eval()

    features = torch.randn((2, len(lat_lons), 2))
    with torch.no_grad():
        x, edge_idx, edge_attr = model(features, torch.tensor(lat_lons))
    assert x.size() == (5882 * 2, 256)
    assert edge_idx.size() == (2, 41162 * 2)


def test_processor():
    processor = Processor().eval()
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))
    model = Encoder(lat_lons).eval()

    features = torch.randn((3, len(lat_lons), 78))
    with torch.no_grad():
        x, edge_idx, edge_attr = model(features)
        out = processor(x, edge_idx, edge_attr)
    assert out.size() == x.size()


def test_decoder():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))
    model = Decoder(lat_lons).eval()
    features = torch.randn((3, len(lat_lons), 78))
    processed = torch.randn((3 * h3.num_hexagons(2), 256))
    with torch.no_grad():
        x = model(processed, features)
    assert x.size() == (3, 2592, 78)


def test_assimilator():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))
    model = AssimilatorDecoder(lat_lons).eval()
    processed = torch.randn((3 * h3.num_hexagons(2), 256))
    with torch.no_grad():
        x = model(processed, 3)
    assert x.size() == (3, 2592, 78)


def test_end2end():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))
    model = Encoder(lat_lons).eval()
    processor = Processor().eval()
    decoder = Decoder(lat_lons).eval()
    features = torch.randn((4, len(lat_lons), 78))
    with torch.no_grad():
        x, edge_idx, edge_attr = model(features)
        out = processor(x, edge_idx, edge_attr)
        pred = decoder(out, features)
    assert pred.size() == (4, 2592, 78)


def test_forecaster():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))
            
    model = GraphWeatherForecaster(
        lat_lons,
        feature_dim=78,
        output_dim=78,
        apply_constraints=False
    )
    
    features = torch.randn((1, len(lat_lons), 78 + 24))
    out = model(features)
    assert not torch.isnan(out).any()

def test_assimilator_model():
    obs_lat_lons = []
    for lat in range(-90, 90, 7):
        for lon in range(0, 180, 6):
            obs_lat_lons.append((lat, lon, np.random.random(1)))
        for lon in 360 * np.random.random(100):
            obs_lat_lons.append((lat, lon, np.random.random(1)))

    output_lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            output_lat_lons.append((lat, lon))
    model = GraphWeatherAssimilator(output_lat_lons=output_lat_lons, analysis_dim=24)

    features = torch.randn((1, len(obs_lat_lons), 2))
    lat_lon_heights = torch.tensor(obs_lat_lons)
    out = model(features, lat_lon_heights)
    assert not torch.isnan(out).any()
    assert not torch.isnan(out).any()


def test_forecaster_and_loss():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))

    # Initialize model with explicit parameters
    model = GraphWeatherForecaster(
        lat_lons,
        feature_dim=78,
        output_dim=78,
        aux_dim=24,
        constraint_type='additive',
        apply_constraints=True,
    )

    batch_size = 2
    features = torch.randn((batch_size, len(lat_lons), 78 + 24))
    out = model(features)
    
    assert out.shape == (batch_size, len(lat_lons), 78)
    
    # Create target with same dimensions
    target = torch.randn_like(out)
    
    # Initialize loss function
    criterion = NormalizedMSELoss(lat_lons=lat_lons, feature_variance=torch.randn((78,)))
    loss = criterion(out, target)
    
    assert not torch.isnan(loss).any()
    assert not torch.isnan(out).any()
    
    loss.backward()


def test_forecaster_and_loss_irregular():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))
    # Jitter the lat and lons
    lat_lons = [(lat + np.random.random(), lon + np.random.random()) for lat, lon in lat_lons]
    criterion = NormalizedMSELoss(lat_lons=lat_lons, feature_variance=torch.randn((78,)))
    model = GraphWeatherForecaster(lat_lons)
    # Add in auxiliary features
    features = torch.randn((2, len(lat_lons), 78 + 24))

    out = model(features)
    loss = criterion(out, torch.rand(out.shape))
    assert not torch.isnan(loss)
    assert not torch.isnan(out).any()
    assert not torch.isnan(out).any()
    loss.backward()


def test_assimilator_model_grad_checkpoint():
    obs_lat_lons = []
    for lat in range(-90, 90, 7):
        for lon in range(0, 180, 6):
            obs_lat_lons.append((lat, lon, np.random.random(1)))
        for lon in 360 * np.random.random(100):
            obs_lat_lons.append((lat, lon, np.random.random(1)))

    output_lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            output_lat_lons.append((lat, lon))
    model = GraphWeatherAssimilator(
        output_lat_lons=output_lat_lons, analysis_dim=24, use_checkpointing=True
    )

    features = torch.randn((1, len(obs_lat_lons), 2))
    lat_lon_heights = torch.tensor(obs_lat_lons)
    out = model(features, lat_lon_heights)
    assert not torch.isnan(out).any()
    assert not torch.isnan(out).any()


def test_forecaster_and_loss_grad_checkpoint():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))
    criterion = NormalizedMSELoss(lat_lons=lat_lons, feature_variance=torch.randn((78,)))
    model = GraphWeatherForecaster(lat_lons, use_checkpointing=True)
    # Add in auxiliary features
    features = torch.randn((2, len(lat_lons), 78 + 24))

    out = model(features)
    loss = criterion(out, torch.rand(out.shape))
    assert not torch.isnan(loss)
    assert not torch.isnan(out).any()
    assert not torch.isnan(out).any()
    loss.backward()


def test_normalized_loss():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))

    # Generate output as strictly positive random features
    out = torch.rand((2, len(lat_lons), 78)) + 0.0001
    feature_variance = out**2
    target = torch.zeros((2, len(lat_lons), 78))

    criterion = NormalizedMSELoss(
        lat_lons=lat_lons, feature_variance=feature_variance, normalize=True
    )
    loss = criterion(out, target)

    assert not torch.isnan(loss)
    # Since feature_variance = out**2 and target = 0, we expect loss = weights
    assert torch.isclose(loss, criterion.weights.expand_as(out.mean(-1)).mean())


def test_image_meta_model():
    batch = 2
    channels = 3
    size = 4
    patch_size = 2
    image = torch.randn((batch, channels, size, size))
    model = ImageMetaModel(
        image_size=size,
        patch_size=patch_size,
        channels=channels,
        depth=1,
        heads=1,
        mlp_dim=7,
        dim_head=64,
    )

    out = model(image)
    assert not torch.isnan(out).any()
    assert out.size() == image.size()


def test_wrapper_image_meta_model():
    batch = 2
    channels = 3
    size = 4
    patch_size = 2
    model = ImageMetaModel(
        image_size=size,
        patch_size=patch_size,
        channels=channels,
        depth=1,
        heads=1,
        mlp_dim=7,
        dim_head=64,
    )
    scale_factor = 3
    big_image = torch.randn((batch, channels, size * scale_factor, size * scale_factor))
    big_model = WrapperImageModel(model, scale_factor)
    out = big_model(big_image)
    assert not torch.isnan(out).any()
    assert out.size() == big_image.size()


def test_meta_model():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))

    batch = 2
    channels = 3
    image_size = 20
    patch_size = 4
    model = MetaModel(
        lat_lons,
        image_size=image_size,
        patch_size=patch_size,
        depth=1,
        heads=1,
        mlp_dim=7,
        channels=channels,
        dim_head=64,
    )
    features = torch.randn((batch, len(lat_lons), channels))

    out = model(features)
    assert not torch.isnan(out).any()
    assert out.size() == features.size()


def test_wrapper_meta_model():
    lat_lons = []
    for lat in range(-90, 90, 5):
        for lon in range(0, 360, 5):
            lat_lons.append((lat, lon))

    batch = 2
    channels = 3
    image_size = 20
    patch_size = 4
    scale_factor = 3
    model = MetaModel(
        lat_lons,
        image_size=image_size,
        patch_size=patch_size,
        depth=1,
        heads=1,
        mlp_dim=7,
        channels=channels,
        dim_head=64,
    )

    big_features = torch.randn((batch, len(lat_lons), channels))
    big_model = WrapperMetaModel(lat_lons, model, scale_factor)
    out = big_model(big_features)

    assert not torch.isnan(out).any()
    assert out.size() == big_features.size()

def test_constrained_forecast():
    lat_lons = [(lat, lon) for lat in (-90, 90) for lon in (-90, 90)]
    model = GraphWeatherForecaster(
        lat_lons,
        constraint_type='softmax',
        apply_constraints=True,
        feature_dim=2,
        aux_dim=0,
        output_dim=2
    )
    
    inp = torch.randn(1, len(lat_lons), 2)
    output = model(inp)   # output shape is [1, 4, 2]
    
    # Convert low-res input graph to grid format: we expect a grid of shape (2,2)
    lr_input = inp[..., :2]
    lr_input_grid = lr_input.permute(0, 2, 1).view(1, 2, 2, 2)
    lr_input_avg = lr_input_grid.mean(dim=(2, 3))
    
    # Convert model output from graph to grid
    output_grid = output.permute(0, 2, 1).view(1, 2, 2, 2)
    lr_output_avg = output_grid.mean(dim=(2, 3))
    
    assert torch.allclose(lr_input_avg, lr_output_avg, atol=0.3), \
         f"Conservation failed: {lr_input_avg} vs {lr_output_avg}"
