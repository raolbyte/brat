from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from playwright.async_api import async_playwright
import os, uuid, shutil, asyncio, time
from collections import defaultdict

app = FastAPI(
    title="BRAT Generator API",
    description="API untuk membuat gambar & video teks gaya BRAT.",
    version="1.0.0"
)


OUTPUT_DIR = "output"
TMP_DIR = "tmp_brat"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)


REQUEST_LIMIT = 10  
TIME_WINDOW = 60    
BAN_DURATION = 300  

request_logs = defaultdict(list)
banned_ips = {}

@app.middleware("http")
async def anti_ddos_middleware(request: Request, call_next):
    client_ip = (
        request.headers.get("CF-Connecting-IP") or
        request.headers.get("X-Forwarded-For", request.client.host)
    ).split(",")[0].strip()

    now = time.time()

    if client_ip in banned_ips:
        if now < banned_ips[client_ip]:
            return JSONResponse(status_code=429, content={"error": "IP diblokir 5 menit karena terlalu banyak request."})
        else:
            del banned_ips[client_ip]

  
    request_logs[client_ip] = [ts for ts in request_logs[client_ip] if now - ts < TIME_WINDOW]
    request_logs[client_ip].append(now)

    
    if len(request_logs[client_ip]) > REQUEST_LIMIT:
        banned_ips[client_ip] = now + BAN_DURATION
        return JSONResponse(status_code=429, content={"error": "Terlalu banyak request. IP diblokir 5 menit."})

    return await call_next(request)


async def delete_file_after_delay(filepath: str, delay: int = 600):
    await asyncio.sleep(delay)
    if os.path.exists(filepath):
        os.remove(filepath)

@app.get("/maker/brat", tags=["maker"])
async def generate_brat(
    request: Request,
    text: str = Query(...),
    background: str = Query(None),
    color: str = Query(None)
):
    if not text.strip():
        return JSONResponse(status_code=400, content={"error": "Teks tidak boleh kosong."})

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(viewport={"width": 1536, "height": 695})
            page = await context.new_page()
            await page.goto("https://www.bratgenerator.com/")

            try:
                await page.click("text=Accept", timeout=3000)
            except:
                pass

            await page.click('#toggleButtonWhite')
            await page.click('#textOverlay')
            await page.click('#textInput')
            await page.fill('#textInput', text)

            await page.evaluate("""(data) => {
                if (data.background) $('.node__content.clearfix').css('background-color', data.background);
                if (data.color) $('.textFitted').css('color', data.color);
            }""", {"background": background, "color": color})

            await asyncio.sleep(0.5)

            element = await page.query_selector('#textOverlay')
            box = await element.bounding_box()

            filename = f"brat_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(OUTPUT_DIR, filename)

            screenshot = await page.screenshot(clip={
                "x": box["x"],
                "y": box["y"],
                "width": 500,
                "height": 440
            })
            with open(filepath, "wb") as f:
                f.write(screenshot)

            await browser.close()

        asyncio.create_task(delete_file_after_delay(filepath))
        base_url = str(request.base_url).rstrip("/")
        return {"status": "success", "image_url": f"{base_url}/download/file/{filename}"}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/maker/bratvid", tags=["maker"])
async def generate_brat_video(
    request: Request,
    text: str = Query(...),
    background: str = Query(None),
    color: str = Query(None)
):
    words = text.strip().split()
    temp_dir = os.path.join(TMP_DIR, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(viewport={"width": 1536, "height": 695})
            page = await context.new_page()
            await page.goto("https://www.bratgenerator.com/")

            try:
                await page.click("text=Accept", timeout=3000)
            except:
                pass

            await page.click('#toggleButtonWhite')
            await page.click('#textOverlay')
            await page.click('#textInput')

            for i in range(len(words)):
                partial_text = " ".join(words[:i + 1])
                await page.fill('#textInput', partial_text)

                await page.evaluate("""(data) => {
                    if (data.background) $('.node__content.clearfix').css('background-color', data.background);
                    if (data.color) $('.textFitted').css('color', data.color);
                }""", {"background": background, "color": color})

                await asyncio.sleep(0.2)

                element = await page.query_selector('#textOverlay')
                box = await element.bounding_box()

                frame_path = os.path.join(temp_dir, f"frame{i:03d}.png")
                screenshot = await page.screenshot(clip={
                    "x": box["x"],
                    "y": box["y"],
                    "width": 500,
                    "height": 440
                })
                with open(frame_path, "wb") as f:
                    f.write(screenshot)

            await context.close()
            await browser.close()

        output_filename = f"bratvid_{uuid.uuid4().hex[:8]}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-framerate", "1.428",
            "-i", os.path.join(temp_dir, "frame%03d.png"),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            output_path
        ]

        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            return JSONResponse(status_code=500, content={"error": stderr.decode()})

        asyncio.create_task(delete_file_after_delay(output_path))
        base_url = str(request.base_url).rstrip("/")
        return {"status": "success", "video_url": f"{base_url}/download/file/{output_filename}"}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@app.get("/download/file/{filename}")
async def download_file(filename: str):
    filepath = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(filepath):
        return Response(open(filepath, "rb").read(), media_type="application/octet-stream")
    return JSONResponse(status_code=404, content={"error": "File tidak ditemukan"})
