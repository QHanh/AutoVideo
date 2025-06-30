from fastapi import Request

from app.controllers.v1.base import new_router
from app.models.schema import (
    VideoScriptRequest,
    VideoScriptResponse,
    VideoTermsRequest,
    VideoTermsResponse,
    VideoScriptPodcastRequest,
    VideoScriptPodcastResponse,
    VideoDialogueRequest,
    VideoDialogueResponse,
)
from app.services import llm
from app.utils import utils

# authentication dependency
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()


@router.post(
    "/scripts",
    response_model=VideoScriptResponse,
    summary="Tạo kịch bản cho video 1 giọng nói",
)
def generate_video_script(request: Request, body: VideoScriptRequest):
    video_script = llm.generate_script(
        video_subject=body.video_subject,
        language=body.video_language,
        paragraph_number=body.paragraph_number,
    )
    response = {"video_script": video_script}
    return utils.get_response(200, response)


@router.post(
    "/scripts-podcast",
    response_model=VideoScriptPodcastResponse,
    summary="Tạo kịch bản cho video podcast",
)
def generate_video_script_podcast(request: Request, body: VideoScriptPodcastRequest):
    video_script_podcast = llm.generate_podcast_script(
        video_subject=body.video_subject,
        video_content=body.video_content,
        language=body.video_language,
    )
    response = {"video_script_podcast": video_script_podcast}
    return utils.get_response(200, response)

@router.post(
    "/dialogues",
    response_model=VideoDialogueResponse,
    summary="Tạo phần đối thoại cho video podcast",
)
def generate_video_dialogue(request: Request, body: VideoDialogueRequest):
    video_dialogue = llm.generate_podcast_dialogue(
        video_content=body.video_content,
        video_script=body.video_script,
        host1=body.host1,
        host2=body.host2,
        tone=body.tone,
        language=body.video_language,
    )
    response = {
        "video_dialogue_tts": video_dialogue["dialogue_tts"], 
        "video_dialogue_subtitle": video_dialogue["dialogue_subtitle"]
        }
    return utils.get_response(200, response)

@router.post(
    "/terms",
    response_model=VideoTermsResponse,
    summary="Tạo các từ khóa tìm kiếm video",
)
def generate_video_terms(request: Request, body: VideoTermsRequest):
    video_terms = llm.generate_terms(
        video_subject=body.video_subject,
        video_script=body.video_script,
        amount=body.amount,
    )
    response = {"video_terms": video_terms}
    return utils.get_response(200, response)
