from starlette.requests import Request
from starlette.responses import StreamingResponse, JSONResponse, Response
from starlette.background import BackgroundTask
from fastapi import FastAPI, HTTPException as FastAPIHTTPException
import httpx
import subprocess
from pydantic import BaseModel
app = FastAPI()

client = httpx.AsyncClient(base_url="http://localhost:7800", timeout=30)

@app.api_route("/ai/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def _reverse_proxy(request: Request, full_path: str):
    # Construct URL from incoming request
    url = httpx.URL(path=full_path, query=request.url.query.encode("utf-8"))
    # print(f"_reverse_proxy {url} full_path {full_path}")

    # Build the proxied request
    rp_req = client.build_request(
        method=request.method,
        url=url,
        headers=request.headers.raw,
        content=request.stream()
    )

    # Send the request with stream=True to allow handling both cases
    try:
        rp_resp = await client.send(rp_req, stream=True)
    except httpx.RequestError as e:
        raise FastAPIHTTPException(status_code=502, detail=str(e))



    # Decide whether to stream or buffer based on content-type
    content_type = rp_resp.headers.get("content-type", "")
    is_stream = "text/event-stream" in content_type or request.headers.get("accept") == "text/event-stream"

    if is_stream:
        return StreamingResponse(
            rp_resp.aiter_raw(),
            status_code=rp_resp.status_code,
            headers=rp_resp.headers,
            background=BackgroundTask(rp_resp.aclose),
        )
    else:
        # Fully read the body into memory
        body = await rp_resp.aread()
        await rp_resp.aclose()
        return Response(
            content=body,
            status_code=rp_resp.status_code,
            headers=rp_resp.headers,
        )
@app.get("/test-litellm")
async def test_litellm_connectivity(request: Request):
    try:
        # This assumes LiteLLM supports GET /v1/models
        async with httpx.AsyncClient() as test_client:
            response = await test_client.get("http://localhost:7800/v1/models")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=502,
            content={"error": "Failed to connect to LiteLLM", "details": str(e)}
        )

@app.get("/sys/top")
async def get_top_mem(request: Request):
    try:
        # Run the command and capture output
        result = subprocess.run(["top", "-b", "-n", "1", "-o", "%MEM"], capture_output=True, text=True)
        if result.returncode == 0:
            return {"output": "\n".join(result.stdout.splitlines()[:20])}
        else:
            return {"error": f"Command failed with code {result.returncode}", "stderr": result.stderr}
    except Exception as e:
        return {"error": str(e)}


class Command(BaseModel):
    cmd: str

@app.post("/bash")
async def bash(command: Command):
    try:
        result = subprocess.run(command.cmd, shell=True, capture_output=True, text=True, timeout=10)
        content = {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
        return result.stdout #JSONResponse(content=json.loads(json.dumps(content)), media_type="application/json", indent=4)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Command timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Route all methods to this proxy
app.add_route("/ai/{path:path}", _reverse_proxy, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
