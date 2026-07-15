import os
import json
import base64
from flask import Flask, request, jsonify, send_from_directory
from PIL import Image, ImageDraw, ImageFont
import io

from evaluator import SaccadeEvaluator

app = Flask(__name__, static_folder='static')

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
STATIC_IMAGES_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'images')
CACHE_FILE = os.path.join(os.path.dirname(__file__), 'stitch_cache.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(STATIC_IMAGES_FOLDER, exist_ok=True)

evaluator = SaccadeEvaluator()

# Helper: Generate mock image if it doesn't exist
def generate_mock_ui_image(filename, screen_type):
    filepath = os.path.join(STATIC_IMAGES_FOLDER, filename)
    if os.path.exists(filepath):
        return
    
    # Create dark themed design mockup (1000x750)
    image = Image.new("RGB", (1000, 750), "#0f0f15") # deep dark obsidian background
    draw = ImageDraw.Draw(image)
    
    if screen_type == "dashboard":
        # Sidebar
        draw.rectangle([0, 0, 220, 750], fill="#161622")
        draw.rectangle([20, 30, 200, 60], fill="#222233") # Logo
        # Sidebar Menu
        for i in range(4):
            draw.rectangle([20, 100 + (i * 50), 180, 130 + (i * 50)], fill="#1b1b2a")
            
        # Header
        draw.rectangle([220, 0, 1000, 80], fill="#161622")
        draw.rectangle([240, 25, 450, 55], fill="#222233") # Search bar
        draw.rectangle([920, 25, 960, 55], fill="#8257e5") # User Avatar
        
        # Grid Cards
        for x_idx in range(3):
            x = 250 + (x_idx * 240)
            draw.rectangle([x, 120, x + 220, 240], fill="#1e1e2f") # Card
            draw.rectangle([x + 20, 140, x + 100, 160], fill="#8257e5") # Card Indicator
            draw.rectangle([x + 20, 180, x + 200, 210], fill="#7f849c") # Text
            
        # Large Table / Content Area
        draw.rectangle([250, 280, 950, 580], fill="#1b1b2a")
        # Rows
        for i in range(5):
            draw.rectangle([270, 310 + (i * 50), 930, 340 + (i * 50)], fill="#222235")
            
        # CTA Button (Highly salient neon purple)
        draw.rectangle([780, 20, 900, 60], fill="#a855f7") # Create Token CTA
        
    elif screen_type == "create_modal":
        # Background underlay
        draw.rectangle([0, 0, 1000, 750], fill="#0a0a0f")
        # Modal body (centered)
        draw.rectangle([250, 120, 750, 620], fill="#161622")
        # Modal Header
        draw.rectangle([280, 160, 500, 190], fill="#8257e5")
        # Form Inputs
        draw.rectangle([280, 240, 720, 290], fill="#1e1e2f")
        draw.rectangle([280, 320, 720, 370], fill="#1e1e2f")
        draw.rectangle([280, 400, 720, 480], fill="#1e1e2f")
        # CTA Button
        draw.rectangle([400, 520, 600, 570], fill="#ec4899") # Submit CTA (Pink)

    image.save(filepath, format="PNG")

# Generate standard stitch cache
def init_stitch_cache():
    if not os.path.exists(CACHE_FILE):
        default_cache = {
            "projects": [
                {
                    "projectId": "6010247233071741212",
                    "title": "Access Token Manager",
                    "screens": [
                        {
                            "screenId": "dashboard",
                            "title": "Token Dashboard",
                            "imageUrl": "/static/images/mock_dashboard.png",
                            "components": [
                                {"label": "Logo", "x": 20, "y": 30, "w": 180, "h": 30},
                                {"label": "Header Nav", "x": 220, "y": 0, "w": 780, "h": 80},
                                {"label": "Create Token CTA", "x": 780, "y": 20, "w": 120, "h": 40},
                                {"label": "Summary Cards", "x": 250, "y": 120, "w": 700, "h": 120},
                                {"label": "Tokens Table", "x": 250, "y": 280, "w": 700, "h": 300}
                            ]
                        },
                        {
                            "screenId": "create_modal",
                            "title": "Create Token View",
                            "imageUrl": "/static/images/mock_modal.png",
                            "components": [
                                {"label": "Modal Container", "x": 250, "y": 120, "w": 500, "h": 500},
                                {"label": "Inputs Area", "x": 280, "y": 240, "w": 440, "h": 240},
                                {"label": "Submit Button", "x": 400, "y": 520, "w": 200, "h": 50}
                            ]
                        }
                    ]
                }
            ]
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(default_cache, f, indent=2)

    # Make sure mock images exist
    generate_mock_ui_image("mock_dashboard.png", "dashboard")
    generate_mock_ui_image("mock_modal.png", "create_modal")

init_stitch_cache()

# CORS Headers
@app.after_request
def add_cors_headers(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response

# Static route for evaluator web page
@app.route('/')
def serve_index():
    return send_from_directory('static', 'index.html')

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

# API: Evaluate Image Upload
@app.route('/api/evaluate', methods=['POST'])
def api_evaluate():
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400
    
    file = request.files['image']
    task_mode = request.form.get('task_mode', 'free_browsing')
    enable_banner_blindness = request.form.get('enable_banner_blindness', 'false').lower() == 'true'
    num_fixations = int(request.form.get('num_fixations', 7))
    ior_radius = int(request.form.get('ior_radius', 80))
    
    # Parse AOIs if supplied
    aois = []
    aois_raw = request.form.get('aois', '[]')
    try:
        aois = json.loads(aois_raw)
    except Exception:
        pass

    try:
        # Load image
        img_bytes = file.read()
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        
        # Saliency calculation
        saliency_map = evaluator.compute_saliency_map(
            image, 
            task_mode=task_mode, 
            enable_banner_blindness=enable_banner_blindness
        )
        
        # Scanpath generation
        fixations = evaluator.generate_scanpath(saliency_map, num_fixations=num_fixations, ior_radius=ior_radius)
        
        # Metrics and recommendations
        metrics = evaluator.calculate_metrics(image, saliency_map, fixations)
        recs = evaluator.generate_recommendations(metrics, fixations, image.width, image.height)
        
        # Evaluate AOIs
        aoi_results = evaluator.evaluate_aois(saliency_map, aois)
        
        # Render Heatmap Overlay
        heatmap_url = evaluator.render_heatmap_overlay(image, saliency_map)
        
        return jsonify({
            "success": True,
            "width": image.width,
            "height": image.height,
            "heatmap_url": heatmap_url,
            "fixations": fixations,
            "metrics": metrics,
            "recommendations": recs,
            "aois": aoi_results
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# API: List Stitch Projects
@app.route('/api/stitch/projects', methods=['GET'])
def api_stitch_projects():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            return jsonify({"projects": cache_data["projects"]})
        return jsonify({"projects": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# API: Evaluate Stitch Screen
@app.route('/api/stitch/evaluate', methods=['POST'])
def api_stitch_evaluate():
    data = request.json or {}
    project_id = data.get('projectId')
    screen_id = data.get('screenId')
    task_mode = data.get('task_mode', 'free_browsing')
    num_fixations = int(data.get('num_fixations', 7))
    ior_radius = int(data.get('ior_radius', 80))
    enable_banner_blindness = data.get('enable_banner_blindness', False)
    
    if not project_id or not screen_id:
        return jsonify({"error": "Missing project or screen ID"}), 400

    try:
        # Load cache
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            
        target_screen = None
        for p in cache_data["projects"]:
            if p["projectId"] == project_id:
                for s in p["screens"]:
                    if s["screenId"] == screen_id:
                        target_screen = s
                        break
        
        if not target_screen:
            return jsonify({"error": "Screen not found"}), 404
            
        # Get image path
        img_path = target_screen["imageUrl"]
        # Convert relative path to absolute
        abs_img_path = os.path.join(os.path.dirname(__file__), img_path.lstrip('/'))
        if not os.path.exists(abs_img_path):
            return jsonify({"error": f"Image file {img_path} not found on server"}), 404
            
        image = Image.open(abs_img_path).convert("RGB")
        
        # Calculate
        saliency_map = evaluator.compute_saliency_map(
            image, 
            task_mode=task_mode, 
            enable_banner_blindness=enable_banner_blindness
        )
        
        fixations = evaluator.generate_scanpath(saliency_map, num_fixations=num_fixations, ior_radius=ior_radius)
        metrics = evaluator.calculate_metrics(image, saliency_map, fixations)
        recs = evaluator.generate_recommendations(metrics, fixations, image.width, image.height)
        
        # Automatically evaluate components as AOIs
        aoi_results = evaluator.evaluate_aois(saliency_map, target_screen.get("components", []))
        
        heatmap_url = evaluator.render_heatmap_overlay(image, saliency_map)
        
        # Read original image base64
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        original_base64 = f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode('utf-8')}"
        
        return jsonify({
            "success": True,
            "width": image.width,
            "height": image.height,
            "original_url": original_base64,
            "heatmap_url": heatmap_url,
            "fixations": fixations,
            "metrics": metrics,
            "recommendations": recs,
            "aois": aoi_results
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# API: Evaluate Workspace URL (Accepts base64 screenshot sent from client or agent)
@app.route('/api/workspace/evaluate', methods=['POST'])
def api_workspace_evaluate():
    data = request.json or {}
    url = data.get('url', 'http://localhost:8000')
    screenshot_b64 = data.get('screenshot')
    task_mode = data.get('task_mode', 'free_browsing')
    num_fixations = int(data.get('num_fixations', 7))
    ior_radius = int(data.get('ior_radius', 80))
    enable_banner_blindness = data.get('enable_banner_blindness', False)
    
    if not screenshot_b64:
        return jsonify({"error": "Missing screenshot data"}), 400
        
    try:
        # Decode base64 screenshot
        if ',' in screenshot_b64:
            screenshot_b64 = screenshot_b64.split(',')[1]
        img_data = base64.b64decode(screenshot_b64)
        image = Image.open(io.BytesIO(img_data)).convert("RGB")
        
        # Calculate
        saliency_map = evaluator.compute_saliency_map(
            image, 
            task_mode=task_mode, 
            enable_banner_blindness=enable_banner_blindness
        )
        
        fixations = evaluator.generate_scanpath(saliency_map, num_fixations=num_fixations, ior_radius=ior_radius)
        metrics = evaluator.calculate_metrics(image, saliency_map, fixations)
        recs = evaluator.generate_recommendations(metrics, fixations, image.width, image.height)
        
        heatmap_url = evaluator.render_heatmap_overlay(image, saliency_map)
        
        return jsonify({
            "success": True,
            "url": url,
            "width": image.width,
            "height": image.height,
            "heatmap_url": heatmap_url,
            "fixations": fixations,
            "metrics": metrics,
            "recommendations": recs
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# API: Refresh Cache from Agent (Admin tool)
@app.route('/api/stitch/refresh', methods=['POST'])
def api_stitch_refresh():
    try:
        data = request.json or {}
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return jsonify({"success": True, "message": "Stitch cache updated successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Starting Saccade UI Evaluator server on http://localhost:5000...")
    app.run(host='0.0.0.0', port=5000, debug=True)
