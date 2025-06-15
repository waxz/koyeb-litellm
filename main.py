from starlette.requests import Request
from starlette.responses import StreamingResponse, JSONResponse, Response
from starlette.background import BackgroundTask
from fastapi import FastAPI, HTTPException as FastAPIHTTPException
import httpx

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


# Route all methods to this proxy
app.add_route("/ai/{path:path}", _reverse_proxy, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
