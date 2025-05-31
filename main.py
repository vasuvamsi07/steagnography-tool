from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from PIL import Image
import io

app = FastAPI()

# Allow CORS for all origins (you can restrict to your frontend domain later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "vasu"

def calc_max_message_length(image: Image.Image):
    width, height = image.size
    # 3 LSBs per pixel (R,G,B)
    total_bits = width * height * 3
    # 8 bits per char, reserve space for delimiter and prefix
    return (total_bits // 8) - len(PREFIX) - 1

def encode_lsb(image: Image.Image, message: str) -> Image.Image:
    encoded = image.copy()
    width, height = image.size
    idx = 0

    # Encode with prefix and null terminator
    message = PREFIX + message + chr(0)
    binary_message = ''.join([format(ord(char), '08b') for char in message])
    msg_len = len(binary_message)

    for y in range(height):
        for x in range(width):
            pixel = list(image.getpixel((x, y)))
            for n in range(3):  # R, G, B
                if idx < msg_len:
                    pixel[n] = pixel[n] & ~1 | int(binary_message[idx])
                    idx += 1
            encoded.putpixel((x, y), tuple(pixel))
            if idx >= msg_len:
                break
        if idx >= msg_len:
            break

    if idx < msg_len:
        raise ValueError("Message too long for this image.")
    return encoded

def decode_lsb(image: Image.Image) -> str:
    width, height = image.size
    bits = []
    for y in range(height):
        for x in range(width):
            pixel = image.getpixel((x, y))
            for n in range(3):  # R, G, B
                bits.append(pixel[n] & 1)
    chars = []
    for b in range(0, len(bits), 8):
        byte = bits[b:b+8]
        if len(byte) < 8:
            break
        char = chr(int(''.join(map(str, byte)), 2))
        if char == chr(0):
            break
        chars.append(char)
    message = ''.join(chars)
    return message

@app.post("/encode")
async def encode(
    file: UploadFile = File(...), 
    message: str = Form(...)
):
    if not file.filename.lower().endswith('.png'):
        raise HTTPException(status_code=400, detail="Only PNG images are allowed.")
    contents = await file.read()
    if len(contents) < 2 * 1024 * 1024 or len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image size must be between 2MB and 10MB.")
    try:
        image = Image.open(io.BytesIO(contents))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image.")
    # Validate message length
    max_len = calc_max_message_length(image)
    if len(message) > max_len:
        return JSONResponse(status_code=400, content={"detail": f"Message too long for this image. Max: {max_len} chars."})
    try:
        encoded = encode_lsb(image, message)
        output = io.BytesIO()
        encoded.save(output, format="PNG")
        output.seek(0)
        return StreamingResponse(output, media_type="image/png", headers={
            "Content-Disposition": f"attachment; filename=encoded_{file.filename}"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/decode")
async def decode(file: UploadFile = File(...)):
    contents = await file.read()
    try:
        image = Image.open(io.BytesIO(contents))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image.")
    message = decode_lsb(image)
    if not message.startswith(PREFIX):
        return JSONResponse(status_code=404, content={"detail": "No hidden message found (prefix not detected)."})
    return {"message": message[len(PREFIX):]}

@app.post("/max_chars")
async def max_chars(file: UploadFile = File(...)):
    contents = await file.read()
    try:
        image = Image.open(io.BytesIO(contents))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image.")
    max_len = calc_max_message_length(image)
    return {"max_chars": max_len}
