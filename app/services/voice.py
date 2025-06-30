import asyncio
import os
import re
from datetime import datetime
from typing import Union
from xml.sax.saxutils import unescape
from edge_tts.submaker import mktimestamp

import edge_tts
import requests
from edge_tts import SubMaker, submaker
from loguru import logger
from moviepy.video.tools import subtitles
# from edge_tts.submaker import mktimestamp

import ffmpeg
from moviepy.audio.io.AudioFileClip import AudioFileClip
import tempfile

from app.config import config
from app.utils import utils


def get_all_azure_voices(filter_locals=None) -> list[str]:
    azure_voices_str = """
Name: vi-VN-HoaiMyNeural
Gender: Female

Name: vi-VN-NamMinhNeural
Gender: Male

Name: en-US-AvaMultilingualNeural-V2
Gender: Female

Name: en-US-AndrewMultilingualNeural-V2
Gender: Male

Name: en-US-EmmaMultilingualNeural-V2
Gender: Female

Name: en-US-BrianMultilingualNeural-V2
Gender: Male

Name: de-DE-FlorianMultilingualNeural-V2
Gender: Male

Name: de-DE-SeraphinaMultilingualNeural-V2
Gender: Female

Name: fr-FR-RemyMultilingualNeural-V2
Gender: Male

Name: fr-FR-VivienneMultilingualNeural-V2
Gender: Female

Name: zh-CN-XiaoxiaoMultilingualNeural-V2
Gender: Female
    """.strip()
    voices = []
   
    pattern = re.compile(r"Name:\s*(.+)\s*Gender:\s*(.+)\s*", re.MULTILINE)
    
    matches = pattern.findall(azure_voices_str)

    for name, gender in matches:
        
        if filter_locals and any(
            name.lower().startswith(fl.lower()) for fl in filter_locals
        ):
            voices.append(f"{name}-{gender}")
        elif not filter_locals:
            voices.append(f"{name}-{gender}")

    voices.sort()
    return voices


def parse_voice_name(name: str):
    name = name.replace("-Female", "").replace("-Male", "").strip()
    return name


def is_azure_v2_voice(voice_name: str):
    voice_name = parse_voice_name(voice_name)
    if voice_name.endswith("-V2"):
        return voice_name.replace("-V2", "").strip()
    return ""


def tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    tts_server: str,
    gemini_key: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    if tts_server == "gemini":
        return get_audio_raw(text, voice_name, voice_file, gemini_key)
    else:
        if is_azure_v2_voice(voice_name):
            # Sử dụng Azure TTS v2 cho các giọng nói đa ngôn ngữ
            return azure_tts_v2(text, voice_name, voice_file)
        # Mặc định sử dụng Azure TTS v1 (Edge TTS)
        return azure_tts_v1(text, voice_name, voice_rate, voice_file)


def convert_rate_to_percent(rate: float) -> str:
    if rate == 1.0:
        return "+0%"
    percent = round((rate - 1.0) * 100)
    if percent > 0:
        return f"+{percent}%"
    else:
        return f"{percent}%"


def azure_tts_v1(
    text: str, voice_name: str, voice_rate: float, voice_file: str
) -> Union[SubMaker, None]:
    voice_name = parse_voice_name(voice_name)
    text = text.strip()
    rate_str = convert_rate_to_percent(voice_rate)
    for i in range(3):
        try:
            logger.info(f"Bắt đầu, tên giọng nói: {voice_name}, thử: {i + 1}")

            async def _do() -> SubMaker:
                communicate = edge_tts.Communicate(text, voice_name, rate=rate_str)
                sub_maker = edge_tts.SubMaker()
                with open(voice_file, "wb") as file:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            file.write(chunk["data"])
                        elif chunk["type"] == "WordBoundary":
                            sub_maker.create_sub(
                                (chunk["offset"], chunk["duration"]), chunk["text"]
                            )
                return sub_maker

            sub_maker = asyncio.run(_do())
            if not sub_maker or not sub_maker.subs:
                logger.warning("Thất bại, sub_maker là None hoặc sub_maker.subs là None")
                continue

            logger.info(f"Hoàn thành, tệp đầu ra: {voice_file}")
            return sub_maker
        except Exception as e:
            logger.error(f"Thất bại, lỗi: {str(e)}")
    return None


def azure_tts_v2(text: str, voice_name: str, voice_file: str) -> Union[SubMaker, None]:
    voice_name = is_azure_v2_voice(voice_name)
    if not voice_name:
        logger.error(f"Tên giọng nói không hợp lệ: {voice_name}")
        raise ValueError(f"Tên giọng nói không hợp lệ: {voice_name}")
    text = text.strip()

    def _format_duration_to_offset(duration) -> int:
        if isinstance(duration, str):
            time_obj = datetime.strptime(duration, "%H:%M:%S.%f")
            milliseconds = (
                (time_obj.hour * 3600000)
                + (time_obj.minute * 60000)
                + (time_obj.second * 1000)
                + (time_obj.microsecond // 1000)
            )
            return milliseconds * 10000

        if isinstance(duration, int):
            return duration

        return 0

    for i in range(3):
        try:
            logger.info(f"Bắt đầu, tên giọng nói: {voice_name}, thử: {i + 1}")

            import azure.cognitiveservices.speech as speechsdk

            sub_maker = SubMaker()

            def speech_synthesizer_word_boundary_cb(evt: speechsdk.SessionEventArgs):
                # print('WordBoundary event:')
                # print('	BoundaryType: {}'.format(evt.boundary_type))
                # print('	AudioOffset: {}ms'.format((evt.audio_offset + 5000)))
                # print('	Duration: {}'.format(evt.duration))
                # print('	Text: {}'.format(evt.text))
                # print('	TextOffset: {}'.format(evt.text_offset))
                # print('	WordLength: {}'.format(evt.word_length))

                duration = _format_duration_to_offset(str(evt.duration))
                offset = _format_duration_to_offset(evt.audio_offset)
                sub_maker.subs.append(evt.text)
                sub_maker.offset.append((offset, offset + duration))

            # Creates an instance of a speech config with specified subscription key and service region.
            speech_key = config.azure.get("speech_key", "")
            service_region = config.azure.get("speech_region", "")
            if not speech_key or not service_region:
                logger.error("Khóa hoặc khu vực Azure Speech chưa được đặt")
                return None

            audio_config = speechsdk.audio.AudioOutputConfig(
                filename=voice_file, use_default_speaker=True
            )
            speech_config = speechsdk.SpeechConfig(
                subscription=speech_key, region=service_region
            )
            speech_config.speech_synthesis_voice_name = voice_name
            # speech_config.set_property(property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestSentenceBoundary,
            #                            value='true')
            speech_config.set_property(
                property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestWordBoundary,
                value="true",
            )

            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
            )
            speech_synthesizer = speechsdk.SpeechSynthesizer(
                audio_config=audio_config, speech_config=speech_config
            )
            speech_synthesizer.synthesis_word_boundary.connect(
                speech_synthesizer_word_boundary_cb
            )

            result = speech_synthesizer.speak_text_async(text).get()
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.success(f"Tổng hợp giọng nói Azure v2 thành công: {voice_file}")
                return sub_maker
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                logger.error(
                    f"Tổng hợp giọng nói Azure v2 bị hủy: {cancellation_details.reason}"
                )
                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    logger.error(
                        f"Lỗi tổng hợp giọng nói Azure v2: {cancellation_details.error_details}"
                    )
            logger.info(f"Hoàn thành, tệp đầu ra: {voice_file}")
        except Exception as e:
            logger.error(f"Thất bại, lỗi: {str(e)}")
    return None


def _format_text(text: str) -> str:
    # text = text.replace("\n", " ")
    text = text.replace("[", " ")
    text = text.replace("]", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace("{", " ")
    text = text.replace("}", " ")
    text = text.strip()
    return text


def create_subtitle(sub_maker: submaker.SubMaker, text: str, subtitle_file: str):

    text = _format_text(text)

    def formatter(idx: int, start_time: float, end_time: float, sub_text: str) -> str:
        """
        1
        00:00:00,000 --> 00:00:02,360
        
        """
        start_t = mktimestamp(start_time).replace(".", ",")
        end_t = mktimestamp(end_time).replace(".", ",")
        return f"{idx}\n{start_t} --> {end_t}\n{sub_text}\n"

    start_time = -1.0
    sub_items = []
    sub_index = 0

    script_lines = utils.split_string_by_punctuations(text)
    script_lines = utils.split_by_word_limit(script_lines, max_words=6)

    def match_line(_sub_line: str, _sub_index: int):
        if len(script_lines) <= _sub_index:
            return ""

        _line = script_lines[_sub_index]
        if _sub_line == _line:
            return script_lines[_sub_index].strip()

        _sub_line_ = re.sub(r"[^\w\s]", "", _sub_line)
        _line_ = re.sub(r"[^\w\s]", "", _line)
        if _sub_line_ == _line_:
            return _line_.strip()

        _sub_line_ = re.sub(r"\W+", "", _sub_line)
        _line_ = re.sub(r"\W+", "", _line)
        if _sub_line_ == _line_:
            return _line.strip()

        return ""

    sub_line = ""

    try:
        for _, (offset, sub) in enumerate(zip(sub_maker.offset, sub_maker.subs)):
            _start_time, end_time = offset
            if start_time < 0:
                start_time = _start_time

            sub = unescape(sub)
            sub_line += sub
            sub_text = match_line(sub_line, sub_index)
            if sub_text:
                sub_index += 1
                line = formatter(
                    idx=sub_index,
                    start_time=start_time,
                    end_time=end_time,
                    sub_text=sub_text,
                )
                sub_items.append(line)
                start_time = -1.0
                sub_line = ""

        if len(sub_items) == len(script_lines):
            with open(subtitle_file, "w", encoding="utf-8") as file:
                file.write("\n".join(sub_items) + "\n")
            try:
                sbs = subtitles.file_to_subtitles(subtitle_file, encoding="utf-8")
                duration = max([tb for ((ta, tb), txt) in sbs])
                logger.info(
                    f"Hoàn thành, tệp phụ đề đã tạo: {subtitle_file}, thời lượng: {duration}"
                )
            except Exception as e:
                logger.error(f"Thất bại, lỗi: {str(e)}")
                os.remove(subtitle_file)
        else:
            logger.warning(
                f"Thất bại, số mục phụ đề: {len(sub_items)}, số dòng kịch bản: {len(script_lines)}"
            )

    except Exception as e:
        logger.error(f"Thất bại, lỗi: {str(e)}")

def convert_raw_to_mp3(raw_file, mp3_file, sample_rate=24000, channels=1):
    """
    Chuyển đổi tệp âm thanh PCM thô sang MP3 bằng ffmpeg.
    sample_format thường là 's16le' (PCM 16bit little-endian), chỉnh lại cho đúng format của bạn.
    """
    (
        ffmpeg
        .input(raw_file, format='s16le', ar=sample_rate, ac=channels)
        .output(mp3_file, acodec='mp3')
        .run(overwrite_output=True)
    )

def get_audio_raw(
    text: str,
    voice_name: str,
    voice_file: str,
    gemini_key: str
) -> submaker.SubMaker:
    text = text.strip()
    url = "https://workflow.doiquanai.vn/webhook/audio"
    payload = {
        "script": text, # Sử dụng dialogue_tts ở đây
        "voice": voice_name,
        "gemini_key": gemini_key
    }
    headers = {
        "Content-Type": "application/json"
    }

    with tempfile.NamedTemporaryFile(delete=False, suffix=".raw") as tmp_raw:
        raw_path = tmp_raw.name

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        with open(raw_path, "wb") as f:
            f.write(response.content)
        convert_raw_to_mp3(raw_path, voice_file, sample_rate=24000, channels=1)
        logger.success(f"Đã lưu TTS Gemini → {voice_file}")
        os.remove(raw_path)
    else:
        logger.error(f"Lỗi khi gọi API TTS Gemini: {response.status_code} - {response.text}")
        return None

    audio_clip = AudioFileClip(voice_file)
    audio_duration = audio_clip.duration  # seconds
    audio_clip.close()
    audio_duration_100ns = int(audio_duration * 10_000_000)

    # Tách các câu thoại từ script
    lines = utils.split_string_by_punctuations(text)
    lines = utils.split_by_word_limit(lines, max_words=6)
    
    if not lines:
        logger.warning(f"Không có dòng nào được trích xuất từ đối thoại phụ đề. Đối thoại gốc: '{text}'")
        return None

    total_chars = sum(len(line) for line in lines)
    
    # Xử lý trường hợp total_chars = 0 để tránh chia cho 0
    if total_chars == 0:
        logger.warning(f"Tổng số ký tự trong đối thoại phụ đề là 0. Không thể ước tính thời lượng ký tự.")
        return None

    char_duration = audio_duration_100ns / total_chars

    sub_maker = submaker.SubMaker()
    current_offset = 0
    for line in lines:
        line_chars = len(line)
        duration = int(line_chars * char_duration)
        sub_maker.subs.append(line)
        sub_maker.offset.append((current_offset, current_offset + duration))
        current_offset += duration

    return sub_maker

def get_audio_podcast_raw(
    dialogue_tts: str,
    dialogue_subtitle: str,
    host1: str,
    host2: str,
    voice1: str,
    voice2: str,
    voice_file: str,
    gemini_key: str,
) -> submaker.SubMaker:
    url = "https://workflow.doiquanai.vn/webhook/audio-podcast"
    payload = {
        "dialogue": dialogue_tts, # Sử dụng dialogue_tts ở đây
        "host1": host1,
        "host2": host2,
        "voice1": voice1,
        "voice2": voice2,
        "gemini_key": gemini_key
    }
    headers = {
        "Content-Type": "application/json"
    }

    with tempfile.NamedTemporaryFile(delete=False, suffix=".raw") as tmp_raw:
        raw_path = tmp_raw.name

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        with open(raw_path, "wb") as f:
            f.write(response.content)
        convert_raw_to_mp3(raw_path, voice_file, sample_rate=24000, channels=1)
        logger.success(f"Đã lưu TTS Gemini → {voice_file}")
        os.remove(raw_path)
    else:
        logger.error(f"Lỗi khi gọi API TTS Gemini: {response.status_code} - {response.text}")
        return None

    audio_clip = AudioFileClip(voice_file)
    audio_duration = audio_clip.duration  # seconds
    audio_clip.close()
    audio_duration_100ns = int(audio_duration * 10_000_000)

    # Tách các câu thoại từ dialogue_subtitle
    lines = utils.split_string_by_punctuations(dialogue_subtitle) # Sử dụng dialogue_subtitle ở đây
    lines = utils.split_by_word_limit(lines, max_words=6)

    if not lines:
        logger.warning(f"Không có dòng nào được trích xuất từ đối thoại phụ đề. Đối thoại gốc: '{dialogue_subtitle}'")
        return None

    total_chars = sum(len(line) for line in lines)
    
    # Xử lý trường hợp total_chars = 0 để tránh chia cho 0
    if total_chars == 0:
        logger.warning(f"Tổng số ký tự trong đối thoại phụ đề là 0. Không thể ước tính thời lượng ký tự.")
        return None

    char_duration = audio_duration_100ns / total_chars

    sub_maker = submaker.SubMaker()
    current_offset = 0
    for line in lines:
        line_chars = len(line)
        duration = int(line_chars * char_duration)
        sub_maker.subs.append(line)
        sub_maker.offset.append((current_offset, current_offset + duration))
        current_offset += duration

    return sub_maker

def get_audio_duration(sub_maker: submaker.SubMaker):
    """
    Tính tổng thời lượng âm thanh từ SubMaker.
    """
    if not sub_maker.offset:
        return 0.0
    # sub_maker.offset lưu thời gian dưới dạng 100 nano giây (ticks), cần chia cho 10^7 để ra giây
    return sub_maker.offset[-1][1] / 10000000

if __name__ == "__main__":
    # Ví dụ sử dụng (chỉ hoạt động nếu bạn cấu hình khóa Azure Speech API hợp lệ trong config.toml)

    # Ví dụ kiểm tra các giọng Azure có sẵn (bao gồm cả V2)
    voices = get_all_azure_voices()
    print(f"Tổng số giọng Azure có sẵn: {len(voices)}")
    # print(voices) # Bỏ comment nếu muốn xem danh sách đầy đủ

    # Ví dụ kiểm tra hàm parse_voice_name và is_azure_v2_voice
    test_voice_name_v2 = "en-US-AvaMultilingualNeural-V2-Female"
    test_voice_name_vn = "vi-VN-HoaiMyNeural-Female"
    print(f"Tên giọng đã phân tích ({test_voice_name_v2}): {parse_voice_name(test_voice_name_v2)}")
    print(f"Là giọng Azure V2 ({test_voice_name_v2})? {is_azure_v2_voice(test_voice_name_v2)}")
    print(f"Là giọng Azure V2 ({test_voice_name_vn})? {is_azure_v2_voice(test_voice_name_vn)}")

    pass # Giữ pass nếu bạn không muốn chạy các ví dụ khi import file này
