"""Unit tests for data quality assurance."""

import pytest
import sys
from pathlib import Path
import numpy as np
from PIL import Image
import importlib.util

# Add devops scripts to path and import data_qa module
devops_scripts_path = Path(__file__).parent.parent.parent / "devops" / "scripts"
data_qa_path = devops_scripts_path / "data-qa.py"

# Load module dynamically
spec = importlib.util.spec_from_file_location("data_qa", data_qa_path)
data_qa_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data_qa_module)

# Import validate_data function
validate_data = data_qa_module.validate_data


# =============================================================================
# Valid Data Tests
# =============================================================================


def test_valid_training_data(training_data_dir):
    """Test validation with valid training data."""
    report = validate_data(training_data_dir)

    assert report["status"] == "PASS"
    assert report["image_count"] == 3
    assert report["mask_count"] == 3
    assert report["valid_pairs"] == 3
    assert len(report["errors"]) == 0


def test_valid_data_statistics(training_data_dir):
    """Test that statistics are collected for valid data."""
    report = validate_data(training_data_dir)

    assert "statistics" in report
    assert "resolution" in report["statistics"]
    assert report["statistics"]["resolution"] == "512x512"
    assert "median_coverage_%" in report["statistics"]


# =============================================================================
# Invalid Data Tests
# =============================================================================


def test_missing_images_directory(temp_dir):
    """Test validation with missing images directory."""
    masks_dir = temp_dir / "masks"
    masks_dir.mkdir()

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert any("Images directory not found" in err for err in report["errors"])


def test_missing_masks_directory(temp_dir):
    """Test validation with missing masks directory."""
    images_dir = temp_dir / "images"
    images_dir.mkdir()

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert any("Masks directory not found" in err for err in report["errors"])


def test_missing_mask_for_image(temp_dir, sample_image):
    """Test validation when image has no corresponding mask."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Create image without mask
    sample_image.save(images_dir / "orphan.jpg")

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert report["image_count"] == 1
    assert report["mask_count"] == 0
    assert any("Missing masks" in err for err in report["errors"])


def test_missing_image_for_mask(temp_dir, sample_mask):
    """Test validation when mask has no corresponding image."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Create mask without image
    sample_mask.save(masks_dir / "orphan.png")

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert report["image_count"] == 0
    assert report["mask_count"] == 1
    assert any("Missing images" in err for err in report["errors"])


def test_wrong_resolution_image(temp_dir, sample_mask):
    """Test validation with wrong image resolution."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Create image with wrong size
    wrong_size_img = Image.new("RGB", (256, 256), color="red")
    wrong_size_img.save(images_dir / "test.jpg")

    # Create matching mask with correct size
    sample_mask.save(masks_dir / "test.png")

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert any("Resolution mismatch" in err for err in report["errors"])


def test_non_binary_mask(temp_dir, sample_image):
    """Test validation with non-binary mask values."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Create valid image
    sample_image.save(images_dir / "test.jpg")

    # Create mask with non-binary values (0-255 grayscale)
    non_binary = np.random.randint(50, 200, (512, 512), dtype=np.uint8)
    Image.fromarray(non_binary, mode="L").save(masks_dir / "test.png")

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert any("Non-binary mask" in err for err in report["errors"])


def test_empty_mask(temp_dir, sample_image):
    """Test validation with empty mask (all zeros)."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Create valid image
    sample_image.save(images_dir / "test.jpg")

    # Create empty mask
    empty_mask = np.zeros((512, 512), dtype=np.uint8)
    Image.fromarray(empty_mask, mode="L").save(masks_dir / "test.png")

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert any("Empty mask" in err for err in report["errors"])


def test_near_empty_mask(temp_dir, sample_image):
    """Test validation with near-empty mask (very few pixels)."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Create valid image
    sample_image.save(images_dir / "test.jpg")

    # Create mask with very few foreground pixels
    mask = np.zeros((512, 512), dtype=np.uint8)
    mask[0:2, 0:2] = 255  # Only 4 pixels
    Image.fromarray(mask, mode="L").save(masks_dir / "test.png")

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert any("Near-empty mask" in err for err in report["errors"])


def test_corrupted_image_file(temp_dir):
    """Test validation with corrupted image file."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Create corrupted file
    (images_dir / "corrupted.jpg").write_bytes(b"not a real image")
    # Create valid mask
    mask = np.zeros((512, 512), dtype=np.uint8)
    Image.fromarray(mask, mode="L").save(masks_dir / "corrupted.png")

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    # Should have an error about the corrupted file


# =============================================================================
# Edge Cases
# =============================================================================


def test_empty_directories(temp_dir):
    """Test validation with empty directories."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert report["image_count"] == 0
    assert report["mask_count"] == 0


def test_mixed_valid_and_invalid_data(temp_dir, sample_image, sample_mask):
    """Test validation with mix of valid and invalid data."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Add valid pair
    sample_image.save(images_dir / "valid.jpg")
    sample_mask.save(masks_dir / "valid.png")

    # Add invalid pair (wrong resolution)
    wrong_img = Image.new("RGB", (256, 256), color="blue")
    wrong_img.save(images_dir / "invalid.jpg")
    sample_mask.save(masks_dir / "invalid.png")

    report = validate_data(temp_dir)

    assert report["status"] == "FAIL"
    assert report["image_count"] == 2
    assert report["mask_count"] == 2
    assert report["valid_pairs"] == 2
    assert len(report["errors"]) > 0


def test_jpg_and_png_images(temp_dir, sample_image, sample_mask):
    """Test that both JPG and PNG images are detected."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Save as JPG
    sample_image.save(images_dir / "test1.jpg")
    sample_mask.save(masks_dir / "test1.png")

    # Save as PNG
    sample_image.save(images_dir / "test2.png")
    sample_mask.save(masks_dir / "test2.png")

    report = validate_data(temp_dir)

    assert report["status"] == "PASS"
    assert report["image_count"] == 2
    assert report["valid_pairs"] == 2


# =============================================================================
# Coverage Statistics Tests
# =============================================================================


def test_coverage_statistics(temp_dir, sample_image):
    """Test that coverage statistics are computed correctly."""
    images_dir = temp_dir / "images"
    masks_dir = temp_dir / "masks"
    images_dir.mkdir()
    masks_dir.mkdir()

    # Create masks with different coverage levels
    for i, coverage_pct in enumerate([10, 30, 50], start=1):
        sample_image.save(images_dir / f"test{i}.jpg")

        # Create mask with specific coverage
        mask = np.zeros((512, 512), dtype=np.uint8)
        num_pixels = int(512 * 512 * coverage_pct / 100)
        mask.flat[:num_pixels] = 255
        np.random.shuffle(mask.flat)

        Image.fromarray(mask, mode="L").save(masks_dir / f"test{i}.png")

    report = validate_data(temp_dir)

    assert report["status"] == "PASS"
    assert "median_coverage_%" in report["statistics"]
    assert "std_coverage_%" in report["statistics"]
    # Median should be around 30%
    assert 25 < report["statistics"]["median_coverage_%"] < 35
