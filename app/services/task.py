import math
import os
import re
# from os import path # Dòng này sẽ được loại bỏ
from typing import List

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams, VideoPodcastParams
from app.services import llm, material, subtitle, video, voice
from app.services import state as sm
from app.utils import utils


def generate_script(task_id, params):
    logger.info("## Đang tạo kịch bản video")
    video_script = params.video_script.strip()
    if not video_script:
        video_script = llm.generate_script(
            video_subject=params.video_subject,
            language=params.video_language,
            paragraph_number=params.paragraph_number,
            gemini_key=params.gemini_key,
            openai_key=params.openai_key
        )
    else:
        logger.debug(f"Kịch bản video đã có: \n{video_script}")

    if not video_script or "Error: " in video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("Không thể tạo kịch bản video.")
        return None

    return video_script

def generate_podcast_script(task_id, params):
    logger.info("## Đang tạo kịch bản podcast")
    podcast_script = params.video_script.strip()
    if not podcast_script:
        podcast_script = llm.generate_podcast_script(
            video_subject=params.video_subject,
            video_content=params.video_content,
            language=params.video_language,
            gemini_key=params.gemini_key,
            openai_key=params.openai_key
        )
    else:
        logger.debug(f"Kịch bản podcast đã có: \n{podcast_script}")
    if not podcast_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("Không thể tạo kịch bản podcast.")
        return None
    
    return podcast_script

def generate_podcast_dialogue(task_id, params):
    logger.info("## Đang tạo đối thoại podcast")
    dialogue_output = {}

    # Kiểm tra nếu đã có sẵn cả hai biến: video_dialogue_tts và video_dialogue_subtitle
    if (
        hasattr(params, 'video_dialogue_tts') and params.video_dialogue_tts and params.video_dialogue_tts.strip() and
        hasattr(params, 'video_dialogue_subtitle') and params.video_dialogue_subtitle and params.video_dialogue_subtitle.strip()
    ):
        logger.debug(f"Đối thoại podcast đã có: \n{params.video_dialogue_tts}")
        dialogue_output = {
            "dialogue_tts": params.video_dialogue_tts,
            "dialogue_subtitle": params.video_dialogue_subtitle
        }
    else:
        # Gọi AI sinh mới nếu chưa có dữ liệu
        dialogue_output = llm.generate_podcast_dialogue(
            video_content=params.video_content,
            video_script=params.video_script,
            host1=params.host1,
            host2=params.host2,
            tone=params.tone,
            language=params.video_language,
            gemini_key=params.gemini_key
        )

    # Kiểm tra kết quả trả về
    if not dialogue_output or "dialogue_tts" not in dialogue_output or "dialogue_subtitle" not in dialogue_output:
        logger.error("Không tạo được đối thoại podcast.")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return None, None

    podcast_dialogue_tts = dialogue_output["dialogue_tts"]
    podcast_dialogue_subtitle = dialogue_output["dialogue_subtitle"]

    # Cập nhật lại params
    params.video_dialogue_tts = podcast_dialogue_tts
    params.video_dialogue_subtitle = podcast_dialogue_subtitle

    # Kiểm tra lỗi từ output
    if not podcast_dialogue_tts or "Error: " in podcast_dialogue_tts:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("Không thể tạo đối thoại podcast.")
        return None, None

    return podcast_dialogue_tts, podcast_dialogue_subtitle



def generate_terms(task_id, params, video_script):
    logger.info("## Đang tạo từ khóa video")
    video_terms = params.video_terms
    if not video_terms:
        video_terms = llm.generate_terms(
            video_subject=params.video_subject, video_script=video_script, amount=5, gemini_key=params.gemini_key, openai_key=params.openai_key
        )
    else:
        if isinstance(video_terms, str):
            video_terms = [term.strip() for term in re.split(r"[,，]", video_terms)]
        elif isinstance(video_terms, list):
            video_terms = [term.strip() for term in video_terms]
        else:
            raise ValueError("video_terms phải là một chuỗi hoặc một danh sách các chuỗi.")

        logger.debug(f"Từ khóa video đã có: {utils.to_json(video_terms)}")

    if not video_terms:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("Không thể tạo từ khóa video.")
        return None

    return video_terms


def save_script_data(task_id, video_script, video_terms, params):
    script_file = os.path.join(utils.task_dir(task_id), "script.json")
    script_data = {
        "script": video_script,
        "search_terms": video_terms,
        "params": params,
    }

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(utils.to_json(script_data))


def generate_audio(task_id, params, video_script):
    logger.info("## Đang tạo âm thanh")
    audio_file = os.path.join(utils.task_dir(task_id), "audio.mp3")
    sub_maker = voice.tts(
        text=video_script,
        voice_name=voice.parse_voice_name(params.voice_name),
        voice_rate=params.voice_rate,
        voice_file=audio_file,
        tts_server=params.tts_server,
        gemini_key=params.gemini_key
    )
    if sub_maker is None:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error(
            """Không thể tạo âm thanh:\n1. Kiểm tra xem ngôn ngữ của giọng nói có khớp với ngôn ngữ của kịch bản video không.\n2. Kiểm tra xem mạng có khả dụng không.\n        """.strip()
        )
        return None, None, None

    audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
    return audio_file, audio_duration, sub_maker


def generate_subtitle(task_id, params, video_script, sub_maker, audio_file):
    if not params.subtitle_enabled:
        logger.info("Tạo phụ đề bị vô hiệu hóa trong cấu hình.")
        return ""

    subtitle_path = os.path.join(utils.task_dir(task_id), "subtitle.srt")
    #subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
    subtitle_provider = params.subtitle_provider
    logger.info(f"## Đang tạo phụ đề, nhà cung cấp: {subtitle_provider}")

    subtitle_created_successfully = False

    if subtitle_provider == "edge":
        if sub_maker:
            voice.create_subtitle(
                text=video_script, sub_maker=sub_maker, subtitle_file=subtitle_path
            )
            if os.path.exists(subtitle_path) and os.path.getsize(subtitle_path) > 0:
                subtitle_created_successfully = True
            else:
                logger.warning("Tệp phụ đề Edge TTS trống hoặc không tồn tại.")
        else:
            logger.warning("Không có SubMaker từ Edge TTS. Hãy thử các nhà cung cấp khác.")

    if subtitle_provider == "whisper_api":
        logger.info("Đang thử tạo phụ đề bằng OpenAI Whisper API...")
        created_path = subtitle.create_api(audio_file=audio_file, subtitle_file=subtitle_path, api_key=params.openai_key)
        if created_path and os.path.exists(created_path) and os.path.getsize(created_path) > 0:
            subtitle_created_successfully = True
            subtitle_path = created_path
        else:
            logger.warning("Tạo phụ đề bằng OpenAI Whisper API thất bại.")

    if subtitle_provider == "whisper_local":
        logger.info("Đang thử tạo phụ đề bằng Faster Whisper cục bộ...")
        created_path = subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
        if created_path and os.path.exists(created_path) and os.path.getsize(created_path) > 0:
            subtitle_created_successfully = True
            subtitle_path = created_path
        else:
            logger.warning("Tạo phụ đề bằng Faster Whisper cục bộ thất bại.")

    if not subtitle_created_successfully:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("Không thể tạo phụ đề bằng bất kỳ nhà cung cấp nào.")
        return None

    return subtitle_path


def get_video_materials(
    task_id: str,
    params,
    video_terms: list,
    audio_duration: float,
) -> List[str] | None:
    if params.video_source == "local":
        logger.info("## Tiền xử lý tài liệu cục bộ")
        materials_list = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        if not materials_list:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "Không tìm thấy tài liệu hợp lệ, vui lòng kiểm tra tài liệu và thử lại."
            )
            return None
        # Trả về danh sách các đường dẫn URL hoặc đường dẫn tệp cục bộ đã xử lý
        return [material_info.url for material_info in materials_list] 
    else:
        logger.info(f"## Đang tải xuống video từ {params.video_source}")
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=video_terms,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_contact_mode=params.video_concat_mode,
            audio_duration=audio_duration * params.video_count,
            max_clip_duration=params.video_clip_duration,
        )
        if not downloaded_videos:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "Không thể tải xuống video, có thể do mạng không khả dụng. Vui lòng kiểm tra kết nối mạng."
            )
            return None
        return downloaded_videos


def generate_final_videos(
    task_id, params, downloaded_videos, audio_file, subtitle_path
):
    final_video_paths = []
    combined_video_paths = []
    video_concat_mode = (
        params.video_concat_mode if params.video_count == 1 else VideoConcatMode.random
    )
    video_transition_mode = params.video_transition_mode

    _progress = 50
    for i in range(params.video_count):
        index = i + 1
        combined_video_path = os.path.join(
            utils.task_dir(task_id), f"combined-{index}.mp4"
        )
        logger.info(f"## Đang kết hợp video: {index} => {combined_video_path}")
        video.combine_videos(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=params.video_aspect,
            video_concat_mode=video_concat_mode,
            video_transition_mode=video_transition_mode,
            max_clip_duration=params.video_clip_duration,
            threads=params.n_threads,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_path = os.path.join(utils.task_dir(task_id), f"final-{index}.mp4")

        logger.info(f"## Đang tạo video fianl thứ {index} => {final_video_path}")
        video.generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_path,
            output_file=final_video_path,
            params=params,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_paths.append(final_video_path)
        combined_video_paths.append(combined_video_path)

    return final_video_paths, combined_video_paths


def start(task_id, params: VideoParams, stop_at: str = "video"):
    logger.info(f"Bắt đầu tác vụ: {task_id}, dừng tại: {stop_at}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    # 1. Tạo kịch bản
    video_script = generate_script(task_id, params)
    if not video_script or "Error: " in video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script}

    # 2. Tạo từ khóa
    video_terms = ""
    if params.video_source != "local":
        video_terms = generate_terms(task_id, params, video_script)
        if not video_terms:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return

    save_script_data(task_id, video_script, video_terms, params)

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": video_script, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # 3. Tạo âm thanh
    audio_file, audio_duration, sub_maker = generate_audio(
        task_id, params, video_script
    )
    if not audio_file:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=30)

    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_file,
        )
        return {"audio_file": audio_file, "audio_duration": audio_duration}

    # 4. Tạo phụ đề
    subtitle_path = generate_subtitle(
        task_id, params, video_script, sub_maker, audio_file
    )

    if stop_at == "subtitle":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            subtitle_path=subtitle_path,
        )
        return {"subtitle_path": subtitle_path}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)

    # 5. Lấy tài liệu video
    downloaded_videos = get_video_materials(
        task_id, params, video_terms, audio_duration
    )
    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 6. Tạo video cuối cùng
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
    )

    if not final_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    logger.success(
        f"Tác vụ {task_id} hoàn thành, đã tạo {len(final_video_paths)} video."
    )

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    return kwargs


def generate_podcast_audio(task_id, params, podcast_dialogue_tts, podcast_dialogue_subtitle):
    logger.info("## Đang tạo audio podcast")
    audio_file = os.path.join(utils.task_dir(task_id), "audio.mp3")
    
    # Gọi voice.get_audio_raw với cả hai loại dialogue
    sub_maker = voice.get_audio_podcast_raw(
        dialogue_tts=podcast_dialogue_tts,
        dialogue_subtitle=podcast_dialogue_subtitle,
        host1=params.host1,
        host2=params.host2,
        voice1=params.voice1,
        voice2=params.voice2,
        voice_file=audio_file,
        gemini_key=params.gemini_key,
    )
    if sub_maker is None:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("Không thể tạo âm thanh podcast.")
        return None, None, None

    audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
    return audio_file, audio_duration, sub_maker


def save_script_podcast_data(task_id, podcast_script, podcast_dialogue, video_terms, params):
    script_file = os.path.join(utils.task_dir(task_id), "script.json")
    script_data = {
        "script": podcast_script,
        "dialogue": podcast_dialogue,
        "search_terms": video_terms,
        "params": params,
    }
    with open(script_file, "w", encoding="utf-8") as f:
        f.write(utils.to_json(script_data))


def start_podcast(task_id, params: VideoPodcastParams, stop_at: str = "video"):
    logger.info(f"Bắt đầu tác vụ podcast: {task_id}, dừng tại: {stop_at}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    # 1. Tạo kịch bản podcast & đối thoại
    podcast_script = generate_podcast_script(task_id, params)
    if not podcast_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    
    podcast_dialogue_tts, podcast_dialogue_subtitle = generate_podcast_dialogue(task_id, params)
    if podcast_dialogue_tts is None or podcast_dialogue_subtitle is None:
        # generate_podcast_dialogue đã cập nhật trạng thái nếu thất bại
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)
    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=podcast_script, dialogue=podcast_dialogue_tts # Lưu dialogue_tts vào trạng thái
        )
        return {"script": podcast_script, "dialogue_tts": podcast_dialogue_tts, "dialogue_subtitle": podcast_dialogue_subtitle}

    # 2. Tạo từ khóa
    video_terms = ""
    if params.video_source != "local":
        # Sử dụng podcast_script cho generate_terms
        video_terms = generate_terms(task_id, params, podcast_script)
        if not video_terms:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return

    save_script_podcast_data(task_id, podcast_script, podcast_dialogue_subtitle, video_terms, params) # Lưu dialogue_subtitle

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": podcast_script, "dialogue_tts": podcast_dialogue_tts, "dialogue_subtitle": podcast_dialogue_subtitle, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # 3. Tạo âm thanh podcast
    audio_file, audio_duration, sub_maker = generate_podcast_audio(
        task_id, params, podcast_dialogue_tts, podcast_dialogue_subtitle
    )
    if not audio_file:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=30)
    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_file,
        )
        return {"audio_file": audio_file, "audio_duration": audio_duration}

    # 4. Tạo phụ đề
    # Sử dụng podcast_dialogue_subtitle để tạo phụ đề
    subtitle_path = generate_subtitle(
        task_id, params, podcast_dialogue_subtitle, sub_maker, audio_file
    )

    if stop_at == "subtitle":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            subtitle_path=subtitle_path,
        )
        return {"subtitle_path": subtitle_path}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)

    # 5. Lấy tài liệu video
    downloaded_videos = get_video_materials(
        task_id, params, video_terms, audio_duration
    )
    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 6. Tạo video cuối cùng
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
    )

    if not final_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    logger.success(
        f"Tác vụ podcast {task_id} hoàn thành, đã tạo {len(final_video_paths)} video."
    )

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": podcast_script,
        "dialogue_tts": podcast_dialogue_tts, # Lưu dialogue_tts
        "dialogue_subtitle": podcast_dialogue_subtitle, # Lưu dialogue_subtitle
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    return kwargs


if __name__ == "__main__":
    pass # Giữ pass nếu không muốn chạy các ví dụ khi import
