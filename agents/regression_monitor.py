import os
import numpy as np
from PIL import Image, ImageChops, ImageDraw
from datetime import datetime, timezone

def compare_screenshots(
    baseline_path: str,
    current_path: str,
    output_diff_dir: str,
    threshold: float = 0.5
) -> dict:
    """
    Compares baseline and current screenshots using Pillow.
    Returns a dict with diff_percentage, status, and diff_image_path (if diff found).
    """
    if not os.path.exists(baseline_path):
        raise FileNotFoundError(f"Baseline screenshot not found at: {baseline_path}")
    if not os.path.exists(current_path):
        raise FileNotFoundError(f"Current screenshot not found at: {current_path}")
        
    os.makedirs(output_diff_dir, exist_ok=True)
    diff_image_path = os.path.join(output_diff_dir, "visual_diff.png")
    
    img1 = Image.open(baseline_path).convert("RGB")
    img2 = Image.open(current_path).convert("RGB")
    
    # If sizes differ, resize current image to match baseline
    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)
        
    # Generate visual difference using NumPy for fast pixel-level comparison
    diff = ImageChops.difference(img1, img2)

    # Convert diff to NumPy array (H x W x 3) for vectorised operations
    diff_arr = np.array(diff)                          # shape: (H, W, 3)
    mask = diff_arr.max(axis=2) > 10                   # True where any channel differs by >10

    non_zero_pixels = int(np.count_nonzero(mask))
    total_pixels = diff_arr.shape[0] * diff_arr.shape[1]
    diff_percentage = (non_zero_pixels / total_pixels) * 100

    # Build highlighted diff image: paint changed pixels red
    highlight_arr = np.array(img1.copy())
    highlight_arr[mask] = [255, 0, 0]                 # vectorised red paint
    highlight_img = Image.fromarray(highlight_arr.astype(np.uint8))
    
    status = "pass"
    if diff_percentage > threshold:
        status = "fail"
        
    # Save the highlighted diff image
    highlight_img.save(diff_image_path)
    
    return {
        "diff_percentage": round(diff_percentage, 2),
        "status": status,
        "diff_image_path": diff_image_path if diff_percentage > 0 else None,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
