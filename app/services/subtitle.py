import json
import os.path
import re
from timeit import default_timer as timer

from faster_whisper import WhisperModel
from loguru import logger
from openai import OpenAI # Import OpenAI client

from app.config import config
from app.utils import utils

model_size = config.whisper.get("model_size", "large-v3")
device = config.whisper.get("device", "cpu")
compute_type = config.whisper.get("compute_type", "int8")
model = None


def create(audio_file, subtitle_file: str = ""):
    global model
    if not model:
        model_path = f"{utils.root_dir()}/models/whisper-{model_size}"
        model_bin_file = f"{model_path}/model.bin"
        if not os.path.isdir(model_path) or not os.path.isfile(model_bin_file):
            model_path = model_size # Sẽ tải xuống nếu không tìm thấy cục bộ

        logger.info(
            f"Đang tải mô hình Faster Whisper: {model_path}, thiết bị: {device}, kiểu tính toán: {compute_type}"
        )
        try:
            model = WhisperModel(
                model_size_or_path=model_path, device=device, compute_type=compute_type
            )
        except Exception as e:
            logger.error(
                f"Không thể tải mô hình Faster Whisper: {e}"
                f"********************************************\n"
                f"Điều này có thể do vấn đề mạng. \n"
                f"Vui lòng tải mô hình thủ công và đặt nó vào thư mục 'models'. \n"
                f"********************************************\n"
            )
            return None

    logger.info(f"Bắt đầu tạo phụ đề bằng Faster Whisper, tệp đầu ra: {subtitle_file}")
    if not subtitle_file:
        subtitle_file = f"{audio_file}.srt"

    segments, info = model.transcribe(
        audio_file,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    logger.info(
        f"Ngôn ngữ được phát hiện bởi Faster Whisper: '{info.language}', xác suất: {info.language_probability:.2f}"
    )

    start = timer()
    subtitles = []

    def recognized(seg_text, seg_start, seg_end):
        seg_text = seg_text.strip()
        if not seg_text:
            return

        msg = "[%.2fs -> %.2fs] %s" % (seg_start, seg_end, seg_text)
        logger.debug(msg)

        subtitles.append(
            {"msg": seg_text, "start_time": seg_start, "end_time": seg_end}
        )

    for segment in segments:
        words_idx = 0
        words_len = len(segment.words)

        seg_start = 0
        seg_end = 0
        seg_text = ""

        if segment.words:
            is_segmented = False
            for word in segment.words:
                if not is_segmented:
                    seg_start = word.start
                    is_segmented = True

                seg_end = word.end
                # If it contains punctuation, then break the sentence.
                seg_text += word.word

                if utils.str_contains_punctuation(word.word):
                    # remove last char
                    seg_text = seg_text[:-1]
                    if not seg_text:
                        continue

                    recognized(seg_text, seg_start, seg_end)

                    is_segmented = False
                    seg_text = ""

                if words_idx == 0 and segment.start < word.start:
                    seg_start = word.start
                if words_idx == (words_len - 1) and segment.end > word.end:
                    seg_end = word.end
                words_idx += 1

        if not seg_text:
            continue

        recognized(seg_text, seg_start, seg_end)

    end = timer()

    diff = end - start
    logger.info(f"Hoàn thành tạo phụ đề bằng Faster Whisper, thời gian đã trôi qua: {diff:.2f} s")

    idx = 1
    lines = []
    for subtitle in subtitles:
        text = subtitle.get("msg")
        if text:
            lines.append(
                utils.text_to_srt(
                    idx, text, subtitle.get("start_time"), subtitle.get("end_time")
                )
            )
            idx += 1

    sub = "\n".join(lines) + "\n"
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write(sub)
    logger.info(f"Đã tạo tệp phụ đề: {subtitle_file}")

    return subtitle_file # Trả về đường dẫn tệp phụ đề đã tạo


def create_api(audio_file: str, subtitle_file: str, api_key: str) -> str | None:
    model_name = config.app.get("openai_whisper_model_name", "whisper-1") # Default to whisper-1
    base_url = config.app.get("openai_base_url", "https://api.openai.com/v1")

    if not api_key:
        logger.error("Khóa API OpenAI chưa được đặt. Vui lòng đặt trong config.toml.")
        return None
    if not os.path.exists(audio_file):
        logger.error(f"Tệp âm thanh không tồn tại: {audio_file}")
        return None

    logger.info(f"Bắt đầu tạo phụ đề bằng OpenAI Whisper API, tệp đầu ra: {subtitle_file}")
    if not subtitle_file:
        subtitle_file = f"{audio_file}.srt"

    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        with open(audio_file, "rb") as audio_f:
            # OpenAI Whisper API có thể trả về định dạng SRT trực tiếp
            # hoặc JSON với các phân đoạn (segments) có dấu thời gian.
            # Yêu cầu định dạng SRT trực tiếp là cách đơn giản nhất.
            transcript = client.audio.transcriptions.create(
                model=model_name,
                file=audio_f,
                response_format="srt" # Yêu cầu định dạng SRT trực tiếp
            )
        
        with open(subtitle_file, "w", encoding="utf-8") as f:
            f.write(transcript)
            
        logger.success(f"Đã tạo tệp phụ đề bằng OpenAI Whisper API: {subtitle_file}")
        return subtitle_file

    except Exception as e:
        logger.error(f"Lỗi khi tạo phụ đề bằng OpenAI Whisper API: {str(e)}")
        return None


if __name__ == "__main__":
    print("--- Thử nghiệm tạo phụ đề từ audio (Faster Whisper) ---")
    test_task_id_fw = "test_subtitle_task_fw"
    task_dir_path_fw = utils.task_dir(test_task_id_fw)
    audio_test_file_fw = os.path.join(task_dir_path_fw, "test_audio_fw.mp3")
    subtitle_test_file_fw = os.path.join(task_dir_path_fw, "test_subtitle_fw.srt")
    print("--- Thử nghiệm tạo phụ đề từ audio (OpenAI Whisper API) ---")
    test_task_id_oa = "test_subtitle_task_oa"
    task_dir_path_oa = utils.task_dir(test_task_id_oa)
    audio_test_file_oa = os.path.join(task_dir_path_oa, "test_audio_oa.mp3")
    subtitle_test_file_oa = os.path.join(task_dir_path_oa, "test_subtitle_oa.srt")

    pass
