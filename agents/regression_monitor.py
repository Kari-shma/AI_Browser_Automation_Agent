import os
from PIL import Image, ImageChops, ImageDraw
from datetime import datetime

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
        
    # Generate visual difference
    diff = ImageChops.difference(img1, img2)
    
    # Get bounding box of differences
    bbox = diff.getbbox()
    
    # Calculate difference percentage
    # We can count non-zero pixels in the diff
    non_zero_pixels = 0
    diff_pixels = diff.load()
    width, height = diff.size
    total_pixels = width * height
    
    # Create diff image for display
    # We overlay the diff on top of the original image
    highlight_img = img1.copy()
    draw = ImageDraw.Draw(highlight_img)
    
    # Check pixels that have a difference above a small noise threshold
    for y in range(height):
        for x in range(width):
            r, g, b = diff_pixels[x, y]
            # If the difference in any channel is > 10 (filter out minor compression artifacts)
            if r > 10 or g > 10 or b > 10:
                non_zero_pixels += 1
                # Draw red overlay with low opacity by drawing a point
                # (to keep it simple without complex pixel access, we can paint a red pixel directly on highlight_img)
                highlight_img.putpixel((x, y), (255, 0, 0))
                
    diff_percentage = (non_zero_pixels / total_pixels) * 100
    
    status = "pass"
    if diff_percentage > threshold:
        status = "fail"
        
    # Save the highlighted diff image
    highlight_img.save(diff_image_path)
    
    return {
        "diff_percentage": round(diff_percentage, 2),
        "status": status,
        "diff_image_path": diff_image_path if diff_percentage > 0 else None,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
