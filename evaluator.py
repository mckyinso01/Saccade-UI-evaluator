import numpy as np
from PIL import Image, ImageFilter, ImageOps
import io
import base64

class SaccadeEvaluator:
    def __init__(self):
        pass

    def compute_saliency_map(self, image: Image.Image, task_mode="free_browsing", enable_banner_blindness=False):
        """
        Computes the bottom-up visual attention saliency map of a UI screenshot.
        Uses difference of Gaussians for intensity contrast, FIND_EDGES for layout detail,
        and RGB variance for color contrast.
        """
        width, height = image.size
        # Downsample to speed up and smooth out high-frequency noise
        scale_factor = 2
        work_w, work_h = width // scale_factor, height // scale_factor
        img_small = image.resize((work_w, work_h), Image.Resampling.BILINEAR)

        # Convert to grayscale
        gray = img_small.convert('L')

        # 1. Intensity Contrast (Difference of Gaussians)
        blur_fine = np.array(gray.filter(ImageFilter.GaussianBlur(radius=2)), dtype=np.float32)
        blur_coarse = np.array(gray.filter(ImageFilter.GaussianBlur(radius=8)), dtype=np.float32)
        intensity_saliency = np.abs(blur_fine - blur_coarse)

        # 2. Edge Density Saliency (Layout Detail/Text)
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edges_smoothed = edges.filter(ImageFilter.GaussianBlur(radius=6))
        edge_saliency = np.array(edges_smoothed, dtype=np.float32)

        # 3. Color Saliency (Saturated / Standout colors)
        img_arr = np.array(img_small, dtype=np.float32)
        if len(img_arr.shape) == 3 and img_arr.shape[2] >= 3:
            r, g, b = img_arr[:,:,0], img_arr[:,:,1], img_arr[:,:,2]
            mean_r, mean_g, mean_b = np.mean(r), np.mean(g), np.mean(b)
            # Distance from mean image color
            color_dist = np.sqrt((r - mean_r)**2 + (g - mean_g)**2 + (b - mean_b)**2)
            # Smooth out color saliency
            color_img = Image.fromarray(np.clip(color_dist, 0, 255).astype(np.uint8))
            color_saliency = np.array(color_img.filter(ImageFilter.GaussianBlur(radius=6)), dtype=np.float32)
        else:
            color_saliency = np.zeros((work_h, work_w), dtype=np.float32)

        # Normalize components to [0, 255]
        def normalize(arr):
            am = np.max(arr)
            return (arr / am * 255.0) if am > 0 else arr

        intensity_saliency = normalize(intensity_saliency)
        edge_saliency = normalize(edge_saliency)
        color_saliency = normalize(color_saliency)

        # Task-Driven Gaze Weight Adjustments (Yarbus Model)
        w_intensity, w_edge, w_color = 0.3, 0.4, 0.3
        if task_mode == "info_search":
            # Looking for text, articles, details
            w_intensity, w_edge, w_color = 0.15, 0.7, 0.15
        elif task_mode == "action_search":
            # Looking for buttons, CTAs, interactive fields
            w_intensity, w_edge, w_color = 0.15, 0.15, 0.7

        # Combined Saliency
        saliency = (w_intensity * intensity_saliency +
                    w_edge * edge_saliency +
                    w_color * color_saliency)

        # Apply Center Bias (20% weight) - human eyes naturally look at the middle
        y_grid, x_grid = np.ogrid[:work_h, :work_w]
        cy, cx = work_h / 2, work_w / 2
        center_bias = np.exp(-(((x_grid - cx)**2) / (2 * (work_w * 0.45)**2) + ((y_grid - cy)**2) / (2 * (work_h * 0.45)**2)))
        center_bias = normalize(center_bias)
        saliency = saliency * (0.8 + 0.2 * (center_bias / 255.0))

        # Apply Banner Blindness Penalty (if enabled)
        if enable_banner_blindness:
            penalty = np.ones((work_h, work_w), dtype=np.float32)
            # Top 10% (header banner) gets 20% penalty
            penalty[:int(work_h * 0.10), :] *= 0.8
            # Right 20% (sidebar) gets 25% penalty
            penalty[:, int(work_w * 0.80):] *= 0.75
            saliency = saliency * penalty

        # final smoothing of saliency map
        saliency_img = Image.fromarray(np.clip(saliency, 0, 255).astype(np.uint8))
        saliency_final = np.array(saliency_img.filter(ImageFilter.GaussianBlur(radius=8)), dtype=np.float32)
        saliency_final = normalize(saliency_final)

        # Resize back to original size for high-resolution overlay coordinates
        saliency_full = np.array(Image.fromarray(saliency_final.astype(np.uint8)).resize((width, height), Image.Resampling.BILINEAR), dtype=np.float32)
        return normalize(saliency_full)

    def generate_scanpath(self, saliency_map: np.ndarray, num_fixations=7, ior_radius=80):
        """
        Generates simulated eye scanpaths using Winner-Take-All (WTA) and Inhibition of Return (IOR).
        """
        height, width = saliency_map.shape
        saliency_work = saliency_map.copy()
        
        fixations = []
        y_indices, x_indices = np.ogrid[:height, :width]

        for i in range(num_fixations):
            # Locate current maximum
            max_idx = np.argmax(saliency_work)
            y_max, x_max = np.unravel_index(max_idx, saliency_work.shape)
            max_val = saliency_work[y_max, x_max]

            if max_val <= 0:
                break

            # Calculate simulated duration (proportional to saliency weight, between 150ms and 500ms)
            duration = int(150 + (max_val / 255.0) * 350)

            fixations.append({
                "id": i + 1,
                "x": int(x_max),
                "y": int(y_max),
                "duration": duration,
                "weight": float(max_val)
            })

            # Apply Inhibition of Return (IOR)
            # Gaussian suppression circle around the current fixation
            suppression = 1.0 - np.exp(-((x_indices - x_max)**2 + (y_indices - y_max)**2) / (2 * ior_radius**2))
            saliency_work = saliency_work * suppression

        return fixations

    def evaluate_aois(self, saliency_map: np.ndarray, aois: list):
        """
        Calculates the Attention Share % for each user-defined Area of Interest (AOI).
        aois format: [{"label": "CTA Button", "x": 100, "y": 200, "w": 150, "h": 50}]
        """
        height, width = saliency_map.shape
        total_saliency = np.sum(saliency_map)
        if total_saliency <= 0:
            total_saliency = 1.0

        aoi_results = []
        for aoi in aois:
            x, y, w, h = int(aoi["x"]), int(aoi["y"]), int(aoi["w"]), int(aoi["h"])
            # Clip bounds to image dimensions
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(width, x + w), min(height, y + h)

            if x2 > x1 and y2 > y1:
                aoi_sum = np.sum(saliency_map[y1:y2, x1:x2])
                share = float((aoi_sum / total_saliency) * 100.0)
            else:
                share = 0.0

            aoi_results.append({
                "label": aoi.get("label", "AOI"),
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "attention_share": round(share, 2)
            })

        return aoi_results

    def calculate_metrics(self, image: Image.Image, saliency_map: np.ndarray, fixations: list):
        """
        Computes visual clutter score, cognitive load index, and reading flow patterns.
        """
        width, height = image.size
        gray = image.convert('L')
        # Edge density (frequency of details)
        edges = np.array(gray.filter(ImageFilter.FIND_EDGES))
        edge_ratio = np.sum(edges > 40) / float(edges.size)
        
        # Clutter score scaled to [0, 100]
        clutter_score = min(100.0, float(edge_ratio * 450.0))
        clutter_rating = "Low"
        if clutter_score > 30:
            clutter_rating = "Optimal"
        if clutter_score > 60:
            clutter_rating = "High (Visual Noise)"

        # Cognitive Load index based on clutter and scattered fixations
        if len(fixations) > 1:
            distances = []
            for i in range(len(fixations) - 1):
                p1, p2 = fixations[i], fixations[i+1]
                dist = np.sqrt((p1["x"] - p2["x"])**2 + (p1["y"] - p2["y"])**2)
                distances.append(dist)
            avg_saccade_len = np.mean(distances)
            cognitive_load = min(100.0, float((clutter_score * 0.6) + (avg_saccade_len / max(width, height) * 100.0 * 0.4)))
        else:
            cognitive_load = clutter_score

        # Determine Flow Pattern Heuristic
        # Gutenberg Diagram & Z/F reading pattern analysis
        flow_pattern = "Scattered"
        flow_score = 50.0
        
        if len(fixations) >= 3:
            # Sort fixations by temporal order
            y_coords = [f["y"] for f in fixations]
            x_coords = [f["x"] for f in fixations]
            
            # Check for Left-to-Right, Top-to-Bottom progressions
            y_diffs = np.diff(y_coords)
            x_diffs = np.diff(x_coords)
            
            # Heuristics
            # 1. Z-Pattern: Top-Left to Top-Right (X increases), diagonal down-left (X decreases, Y increases), Bottom-Left to Bottom-Right (X increases)
            swings_x = np.sign(x_diffs)
            swings_y = np.sign(y_diffs)
            
            if len(x_diffs) >= 3 and swings_x[0] > 0 and swings_x[1] < 0 and swings_x[2] > 0 and swings_y[1] > 0:
                flow_pattern = "Z-Pattern"
                flow_score = 88.0
            # 2. F-Pattern: Scanning top horizontally, then scanning slightly lower horizontally, then vertical down left
            elif len(y_coords) >= 4 and y_coords[0] < height * 0.3 and y_coords[1] < height * 0.3 and y_coords[2] < height * 0.6 and x_coords[2] < width * 0.4:
                flow_pattern = "F-Pattern"
                flow_score = 82.0
            # 3. Clean sequential top-down
            elif all(yd >= -10 for yd in y_diffs):
                flow_pattern = "Linear Top-Down"
                flow_score = 92.0
            else:
                flow_pattern = "Scattered / Exploratory"
                flow_score = min(60.0, 100.0 - cognitive_load)

        return {
            "clutter_score": round(clutter_score, 1),
            "clutter_rating": clutter_rating,
            "cognitive_load": round(cognitive_load, 1),
            "flow_pattern": flow_pattern,
            "flow_score": round(flow_score, 1)
        }

    def generate_recommendations(self, metrics: dict, fixations: list, width: int, height: int):
        """
        Generates automated UX critique layout suggestions.
        """
        recs = []
        clutter = metrics["clutter_score"]
        flow = metrics["flow_pattern"]
        
        # Clutter checks
        if clutter > 60:
            recs.append("Visual clutter is high. Reduce background borders, decrease text density, and add more whitespace to lower cognitive load.")
        
        # Focal anchor checks
        if len(fixations) > 0:
            first_fix = fixations[0]
            if first_fix["x"] < width * 0.15 or first_fix["x"] > width * 0.85 or first_fix["y"] < height * 0.1 or first_fix["y"] > height * 0.9:
                recs.append("The primary focal point (Fixation 1) is located at the margins. Consider centering important visual anchors or headlines.")
        
        # CTA checking (heuristics: CTA buttons are usually in the middle-to-bottom or top-right)
        cta_spotted = False
        for f in fixations[:3]:
            if f["weight"] > 180:
                cta_spotted = True
                break
        if not cta_spotted:
            recs.append("Visual contrast on Call-to-Actions (CTAs) is low. Primary buttons are not captured in the first 3 fixations. Increase CTA color saturation or contrast relative to the background.")

        # Flow pattern suggestion
        if flow == "Scattered / Exploratory":
            recs.append("Visual flow is scattered. Align key structural components horizontally or vertically to guide the user's scan path along a clean Z-pattern or linear layout.")
        elif flow == "F-Pattern":
            recs.append("F-Pattern detected. This is optimal for text readability, but ensure that important calls-to-action are placed in the horizontal headers, not lost down the vertical scroll.")
            
        if not recs:
            recs.append("Layout is clean and balanced. Visual weight is correctly distributed across primary visual anchors.")
            
        return recs

    def render_heatmap_overlay(self, image: Image.Image, saliency_map: np.ndarray):
        """
        Applies a jet-like colormap overlay onto the original screenshot.
        """
        saliency_norm = saliency_map / 255.0
        h, w = saliency_map.shape
        
        heatmap_r = np.zeros((h, w), dtype=np.uint8)
        heatmap_g = np.zeros((h, w), dtype=np.uint8)
        heatmap_b = np.zeros((h, w), dtype=np.uint8)
        
        for y in range(h):
            for x in range(w):
                v = saliency_norm[y, x]
                if v < 0.25:
                    heatmap_b[y, x] = 255
                    heatmap_g[y, x] = int(v * 4.0 * 255)
                elif v < 0.5:
                    heatmap_g[y, x] = 255
                    heatmap_b[y, x] = int((1.0 - (v - 0.25) * 4.0) * 255)
                elif v < 0.75:
                    heatmap_g[y, x] = 255
                    heatmap_r[y, x] = int((v - 0.5) * 4.0 * 255)
                else:
                    heatmap_r[y, x] = 255
                    heatmap_g[y, x] = int((1.0 - (v - 0.75) * 4.0) * 255)

        heatmap_arr = np.stack([heatmap_r, heatmap_g, heatmap_b], axis=-1)
        heatmap_img = Image.fromarray(heatmap_arr)
        
        buffered = io.BytesIO()
        heatmap_img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{img_str}"
