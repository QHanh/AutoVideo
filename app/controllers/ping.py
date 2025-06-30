from fastapi import APIRouter, Request

router = APIRouter()


@router.get(
    "/ping",
    tags=["Health Check"],
    description="Kiểm tra tính sẵn sàng của dịch vụ",
    response_description="pong",
)
def ping(request: Request) -> str:
    return "pong"
