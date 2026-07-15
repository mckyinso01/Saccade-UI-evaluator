import sys
import numpy as np
from PIL import Image, ImageDraw

# Add current folder to path
sys.path.append(".")
from evaluator import SaccadeEvaluator

def run_test():
    print("=== SACCADE EVALUATOR PRE-FLIGHT TEST ===")
    
    # 1. Create a synthetic UI screenshot (800x600 px)
    # White background representing a web page
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    
    # A dark header bar (top)
    draw.rectangle([0, 0, 800, 80], fill="#1e1e2e")
    
    # Logo text inside header
    draw.text((30, 30), "MOCK LOGO", fill="white")
    
    # Hero Title (large dark gray text block)
    draw.rectangle([200, 150, 600, 200], fill="#313244")
    
    # Subtext block (smaller light gray block)
    draw.rectangle([250, 220, 550, 250], fill="#7f849c")
    
    # Primary CTA button: Bright, highly saturated purple block (should be highly salient!)
    draw.rectangle([320, 280, 480, 330], fill="#cba6f7")
    
    # Secondary text or elements (bottom center)
    draw.rectangle([100, 400, 700, 500], fill="#e6e9ef")

    # 2. Instantiate and run SaccadeEvaluator
    evaluator = SaccadeEvaluator()
    print("Synthetic UI generated. Computing saliency map...")
    
    saliency_map = evaluator.compute_saliency_map(
        image, 
        task_mode="free_browsing", 
        enable_banner_blindness=True
    )
    
    print("Saliency map shape:", saliency_map.shape)
    assert saliency_map.shape == (600, 800), "Saliency map dimensions mismatch!"
    
    # 3. Generate scanpath (fixations)
    print("Generating simulated gaze scanpath (7 fixations)...")
    fixations = evaluator.generate_scanpath(saliency_map, num_fixations=7, ior_radius=70)
    
    print(f"Generated {len(fixations)} fixations:")
    for f in fixations:
        print(f"  Fixation {f['id']}: coord=({f['x']}, {f['y']}), weight={f['weight']:.1f}, duration={f['duration']}ms")
        
    assert len(fixations) > 0, "No fixations generated!"
    
    # 4. Define and evaluate Areas of Interest (AOIs)
    # Define an AOI around the CTA button (coordinates match the CTA button drawn above)
    aois = [
        {"label": "CTA Button", "x": 320, "y": 280, "w": 160, "h": 50},
        {"label": "Header Bar", "x": 0, "y": 0, "w": 800, "h": 80}
    ]
    print("Evaluating Areas of Interest (AOIs)...")
    aoi_results = evaluator.evaluate_aois(saliency_map, aois)
    
    for a in aoi_results:
        print(f"  AOI '{a['label']}': Attention Share = {a['attention_share']}%")
        
    # 5. Compute layout metrics and recommendations
    print("Computing metrics and suggestions...")
    metrics = evaluator.calculate_metrics(image, saliency_map, fixations)
    recs = evaluator.generate_recommendations(metrics, fixations, 800, 600)
    
    print("\nMetrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
        
    print("\nRecommendations:")
    for r in recs:
        print(f"  - {r}")
        
    # 6. Test Heatmap rendering
    print("\nRendering heatmap...")
    heatmap_uri = evaluator.render_heatmap_overlay(image, saliency_map)
    assert heatmap_uri.startswith("data:image/png;base64,"), "Heatmap URI format is invalid!"
    print("Heatmap overlay base64 generated successfully.")
    
    print("\n=== ALL TESTS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_test()
