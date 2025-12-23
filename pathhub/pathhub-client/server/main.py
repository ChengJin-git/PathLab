from fastapi import FastAPI, Body
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import sys
import signal
import io
from PIL import Image, ImageDraw
import random

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "alive"}

@app.post("/inference")
def inference(x: int = Body(...), y: int = Body(...), w: int = Body(...), h: int = Body(...)):
    # Generate a random mask
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw a random circle or shape
    cx, cy = w // 2, h // 2
    r = min(w, h) // 3
    color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 128)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

# Mock Tile Server
@app.get("/tile/{z}/{x}/{y}")
def get_tile(z: int, x: int, y: int):
    # Generate a mock tile
    img = Image.new('RGB', (256, 256), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 255, 255), outline=(200, 200, 200))
    draw.text((10, 10), f"Tile: {z}/{x}/{y}", fill=(0, 0, 0))
    
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    # Enable auto-reload for better DX
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
