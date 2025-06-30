import glob
import itertools
import os
import random
import numpy as np
import gc
import shutil
from typing import List
from loguru import logger
from PIL import Image, ImageDraw, ImageFont
from moviepy.video.fx.Resize import Resize
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
    VideoClip,
    ImageClip
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import ImageFont
import re
from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
    VideoPodcastParams,
)
from app.services.utils import video_effects
from app.utils import utils

class SubClippedVideoClip:
    def __init__(self, file_path, start_time=None, end_time=None, width=None, height=None, duration=None):
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.width = width
        self.height = height
        if duration is None:
            self.duration = end_time - start_time
        else:
            self.duration = duration

    def __str__(self):
        return f"SubClippedVideoClip(file_path={self.file_path}, start_time={self.start_time}, end_time={self.end_time}, duration={self.duration}, width={self.width}, height={self.height})"


audio_codec = "aac"
# video_codec = "h264_nvenc"
video_codec = "libx264"
fps = 30
preset = "ultrafast"

def close_clip(clip):
    if clip is None:
        return
        
    try:
        # close main resources
        if hasattr(clip, 'reader') and clip.reader is not None:
            clip.reader.close()
            
        # close audio resources
        if hasattr(clip, 'audio') and clip.audio is not None:
            if hasattr(clip.audio, 'reader') and clip.audio.reader is not None:
                clip.audio.reader.close()
            del clip.audio
            
        # close mask resources
        if hasattr(clip, 'mask') and clip.mask is not None:
            if hasattr(clip.mask, 'reader') and clip.mask.reader is not None:
                clip.mask.reader.close()
            del clip.mask
            
        # handle child clips in composite clips
        if hasattr(clip, 'clips') and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)
            
        # clear clip list
        if hasattr(clip, 'clips'):
            clip.clips = []
            
    except Exception as e:
        logger.error(f"Không thể đóng clip: {str(e)}")
    
    del clip
    gc.collect()

def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]
        
    for file in files:
        try:
            os.remove(file)
        except:
            pass

def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        if not files:
            logger.warning("Không tìm thấy tệp nhạc nền nào trong thư mục. Vui lòng thêm tệp .mp3 vào resource/songs.")
            return ""
        return random.choice(files)

    return ""

def combine_images(
    combined_video_path: str,
    image_paths: List[str],
    audio_file: str,
    image_duration: float = 2.0,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    threads: int = 2
) -> str:

    logger.info("🔄 Bắt đầu quá trình kết hợp image")
    # Load audio
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"🎵 Thời lượng audio: {audio_duration:.2f} giây")
    output_dir = os.path.dirname(combined_video_path)
    # Tính kích thước video theo tỉ lệ
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    logger.info(f"📐 Kích thước đầu ra: {video_width}x{video_height}")

    # Tạo danh sách clip ảnh
    image_clips = []
    for img_path in image_paths:
        clip = ImageClip(img_path).with_duration(image_duration)
        # Resize ảnh theo chiều cao, giữ tỉ lệ
        clip = clip.resize(height=video_height)
        # Tạo background đen nếu kích thước ảnh nhỏ hơn video
        if clip.size != (video_width, video_height):
            bg = ColorClip(size=(video_width, video_height), color=(0,0,0), duration=clip.duration)
            clip = CompositeVideoClip([bg, clip.with_position("center")])
        image_clips.append(clip)

    # Sắp xếp clip
    if video_concat_mode == VideoConcatMode.random:
        logger.info("🔀 Trộn ngẫu nhiên các image")
        random.shuffle(image_clips)

    # Thêm hiệu ứng chuyển cảnh
    def apply_transition(clip):
        if video_transition_mode is None or video_transition_mode == "none":
            return clip
        side = random.choice(["top", "bottom", "left", "right"])
        if video_transition_mode == "fade_in":
            return clip.crossfadein(1)
        elif video_transition_mode == "fade_out":
            return clip.crossfadeout(1)
        elif video_transition_mode == "slide_in":
            # slide in effect tự custom, ví dụ di chuyển clip từ bên ngoài vào
            return clip.with_start(0).with_position(lambda t: ("center", int(video_height * (1 - t))) if t<=1 else ("center", 0))
        elif video_transition_mode == "slide_out":
            return clip.with_start(0).with_position(lambda t: ("center", int(video_height * t)) if t<=1 else ("center", video_height))
        elif video_transition_mode == "shuffle":
            effects = ["fade_in", "fade_out", "slide_in", "slide_out"]
            choice = random.choice(effects)
            return apply_transition(clip.with_duration(clip.duration), video_transition_mode=choice)
        else:
            return clip

    image_clips = [apply_transition(c) for c in image_clips]

    # Ghép clip ảnh thành video
    final_clip = concatenate_videoclips(image_clips, method="compose")

    # Lặp lại clip nếu tổng thời lượng nhỏ hơn audio
    while final_clip.duration < audio_duration:
        final_clip = concatenate_videoclips([final_clip, final_clip], method="compose")

    # Cắt video cho vừa với audio
    final_clip = final_clip.subclipped(0, audio_duration)

    # Gán audio
    final_clip = final_clip.with_audio(audio_clip)

    # Xuất video
    logger.info("🎥 Đang render video đầu ra...")
    final_clip.write_videofile(
        combined_video_path,
        fps=fps,
        threads=threads,
        audio_codec="aac",
        preset=preset,
        logger="bar",
        temp_audiofile_path=output_dir
    )

    # Đóng clip để giải phóng tài nguyên
    final_clip.close()
    audio_clip.close()
    for c in image_clips:
        c.close()

    logger.success(f"✅ Kết hợp image hoàn tất! Đã lưu tại: {combined_video_path}")
    return combined_video_path

def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 4
) -> str:

    logger.info("🔄 Bắt đầu quá trình kết hợp video")
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"🎵 Thời lượng audio: {audio_duration:.2f} giây")
    output_dir = os.path.dirname(combined_video_path)
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    logger.info(f"📐 Kích thước đầu ra: {video_width}x{video_height}")

    subclips = []
    for video_path in video_paths:
        try:
            clip = VideoFileClip(video_path)
        except Exception as e:
            logger.warning(f"❌ Không thể mở video: {video_path}, bỏ qua. Lỗi: {str(e)}")
            continue

        duration = clip.duration
        start = 0
        while start < duration:
            end = min(start + max_clip_duration, duration)
            if end - start >= 1:
                subclips.append(SubClippedVideoClip(video_path, start, end, *clip.size))
            start = end
            if video_concat_mode == VideoConcatMode.sequential:
                break
        clip.close()

    if video_concat_mode == VideoConcatMode.random:
        logger.info("🔀 Trộn ngẫu nhiên các clip")
        random.shuffle(subclips)

    video_clips = []
    total_duration = 0
    logger.info(f"🎞️ Đang xử lý {len(subclips)} subclip")

    for i, item in enumerate(subclips):
        if total_duration > audio_duration:
            break
        try:
            clip = VideoFileClip(item.file_path).subclipped(item.start_time, item.end_time)
            
            if clip.size != (video_width, video_height):
                clip = clip.with_effects([Resize(height=video_height)])               
                bg = ColorClip(size=(video_width, video_height), color=(0, 0, 0), duration=clip.duration)
                new_clip = CompositeVideoClip([bg, clip.with_position("center")])

                if clip.audio:
                    new_clip = new_clip.with_audio(clip.audio)

                clip = new_clip

            # 🌀 Apply transition
            shuffle_side = random.choice(["top", "bottom", "left", "right"])
            if video_transition_mode == VideoTransitionMode.none:
                pass
            elif video_transition_mode == VideoTransitionMode.fade_in:
                clip = video_effects.fadein_transition(clip, 1)
            elif video_transition_mode == VideoTransitionMode.fade_out:
                clip = video_effects.fadeout_transition(clip, 1)
            elif video_transition_mode == VideoTransitionMode.slide_in:
                clip = video_effects.slidein_transition(clip, 1, shuffle_side)
            elif video_transition_mode == VideoTransitionMode.slide_out:
                clip = video_effects.slideout_transition(clip, 1, shuffle_side)
            elif video_transition_mode == VideoTransitionMode.shuffle:
                transitions = [
                    lambda c: video_effects.fadein_transition(c, 1),
                    lambda c: video_effects.fadeout_transition(c, 1),
                    lambda c: video_effects.slidein_transition(c, 1, shuffle_side),
                    lambda c: video_effects.slideout_transition(c, 1, shuffle_side),
                ]
                clip = random.choice(transitions)(clip)

            video_clips.append(clip)
            total_duration += clip.duration
        except Exception as e:
            logger.warning(f"❌ Clip lỗi: {item.file_path}, {str(e)}")

    # Lặp lại nếu chưa đủ
    if total_duration < audio_duration:
        logger.warning("⏳ Tổng video ngắn hơn audio, lặp lại clip...")
        initial_len = len(video_clips)
        for clip in video_clips[:]:
            if total_duration >= audio_duration:
                break
            video_clips.append(clip.copy())
            total_duration += clip.duration
        logger.info(f"🔁 Đã lặp thêm {len(video_clips) - initial_len} clip")

    logger.info("🧩 Đang kết hợp toàn bộ clip...")
    final_video = concatenate_videoclips(video_clips, method="compose").with_audio(audio_clip)

    logger.info("🎥 Đang render video đầu ra...")
    final_video.write_videofile(
        combined_video_path,
        threads=threads,
        logger="bar",
        temp_audiofile_path=output_dir,
        audio_codec="aac",
        fps=fps,
        preset=preset
    )

    # Cleanup
    for clip in video_clips:
        clip.close()
    audio_clip.close()
    final_video.close()

    logger.success(f"✅ Kết hợp video hoàn tất! Đã lưu tại: {combined_video_path}")
    return combined_video_path

def wrap_text(text, max_width, font="Arial", fontsize=60):
    # Create ImageFont
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    processed = True

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ""
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = "\n".join(_wrapped_lines_).strip()
        height = len(_wrapped_lines_) * height
        return result, height

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ""
    for char in chars: # Sửa đổi vòng lặp từ word thành char
        _txt_ += char
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ""
    if _txt_: # Đảm bảo thêm phần còn lại nếu có
        _wrapped_lines_.append(_txt_)
    result = "\n".join(_wrapped_lines_).strip()
    height = len(_wrapped_lines_) * height
    return result, height

def typewriter_clip(text, font_path, font_size,
                    color="white", stroke_color=None, stroke_width=0,
                    duration=3, chars_per_sec=18,
                    bg=None, txt_align="center"):
    """
    Trả về VideoClip hiển thị text 'gõ' từng ký tự.
    """
    font = ImageFont.truetype(font_path, font_size)
    W, H = font.getbbox(text)[2:]           # ước tính size
    margin = 20
    canvas_w = int(W * 1.1) + margin * 2
    canvas_h = font_size * 3                # đủ chỗ cho 2-3 dòng

    def make_frame(t):
        n = max(1, int(chars_per_sec * t))
        img = Image.new("RGBA", (canvas_w, canvas_h),
                        color=(0, 0, 0, 0) if bg is None else bg)
        draw = ImageDraw.Draw(img)
        slice_txt = text[:n]

        # căn giữa
        w_txt, h_txt = font.getbbox(slice_txt)[2:]
        x = (canvas_w - w_txt) // 2 if txt_align == "center" else margin
        y = (canvas_h - h_txt) // 2
        if stroke_width:
            draw.text((x, y), slice_txt, font=font,
                      fill=stroke_color, stroke_width=stroke_width)
        draw.text((x, y), slice_txt, font=font, fill=color)

        return np.array(img)

    return VideoClip(frame_function=make_frame,
                     duration=duration).with_fps(24)

def typewriter_word_clip(text,
                         font_path,
                         font_size,
                         color="white",
                         stroke_color=None,
                         stroke_width=0,
                         duration=3,
                         words_per_sec=3,
                         video_w=1080, video_h=1920,
                         subtitle_position="center",
                         custom_pos=70):
    words = re.findall(r"\S+", text)
    font  = ImageFont.truetype(font_path, font_size)

    # ------- hàm tạo frame ----------
    def make_frame(t):
        img = Image.new("RGBA", (video_w, video_h), (0,0,0,0))
        draw = ImageDraw.Draw(img)

        idx = int(t * words_per_sec)
        if idx < len(words):
            word = words[idx]
            w, h = font.getbbox(word)[2:]
            # ----- xác định toạ độ Y theo subtitle_position -----
            if subtitle_position == "bottom":
                y = int(video_h*0.95 - h)
            elif subtitle_position == "top":
                y = int(video_h*0.05)
            elif subtitle_position == "custom":
                margin, max_y = 10, video_h - h - 10
                y = max(margin,
                        min((video_h - h) * custom_pos/100, max_y))
            else:                              # "center"
                y = (video_h - h)//2
            x = (video_w - w)//2               # luôn căn giữa ngang

            if stroke_width:
                draw.text((x, y), word, font=font,
                          fill=stroke_color, stroke_width=stroke_width)
            draw.text((x, y), word, font=font, fill=color)

        return np.array(img)

    clip_dur = max(duration, len(words)/words_per_sec)
    return VideoClip(frame_function=make_frame,
                     duration=clip_dur).with_fps(24)

def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams
):
    font_size    = int(round(params.font_size))
    stroke_width = int(round(params.stroke_width))
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"Đang tạo video: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② âm thanh: {audio_path}")
    logger.info(f"  ③ phụ đề: {subtitle_path}")
    logger.info(f"  ④ đầu ra: {output_file}")

    output_dir = os.path.dirname(output_file)

    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = "Charm-Bold.ttf"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

        logger.info(f"  ⑤ phông chữ: {font_path}")

    def create_text_clip(subtitle_item):
        type_subtitle = params.type_subtitle
        (start_t, end_t), phrase = subtitle_item
        duration = end_t - start_t
        if type_subtitle == "normal":
            max_width = video_width * 0.9
            wrapped_txt, txt_height = wrap_text(
                phrase, max_width=max_width, font=font_path, fontsize=params.font_size
            )
            interline = int(params.font_size * 0.25)
            size=(int(max_width), int(txt_height + params.font_size * 0.25 + (interline * (wrapped_txt.count("\n") + 1))))

            _clip = TextClip(
                text=wrapped_txt,
                font=font_path,
                font_size=font_size,
                color=params.text_fore_color,
                bg_color=params.text_background_color,
                stroke_color=params.stroke_color,
                stroke_width=stroke_width,
                interline=interline,
                size=size,
            )
            duration = subtitle_item[0][1] - subtitle_item[0][0]
            _clip = _clip.with_start(subtitle_item[0][0])
            _clip = _clip.with_end(subtitle_item[0][1])
            _clip = _clip.with_duration(duration)
            if params.subtitle_position == "bottom":
                _clip = _clip.with_position(("center", video_height * 0.95 - _clip.h))
            elif params.subtitle_position == "top":
                _clip = _clip.with_position(("center", video_height * 0.05))
            elif params.subtitle_position == "custom":
                # Ensure the subtitle is fully within the screen bounds
                margin = 10  # Additional margin, in pixels
                max_y = video_height - _clip.h - margin
                min_y = margin
                custom_y = (video_height - _clip.h) * (params.custom_position / 100)
                custom_y = max(
                    min_y, min(custom_y, max_y)
                )  # Bỏ qua giá trị ngoài khoảng
                _clip = _clip.with_position(("center", custom_y))
            else:  # trung tâm
                _clip = _clip.with_position(("center", "center"))
            return _clip

        elif type_subtitle == "typewriter":
            buffer_time = 0.3
            clip = typewriter_clip(
                text=phrase,
                font_path=font_path,
                font_size=font_size,
                color=params.text_fore_color,
                stroke_color=params.stroke_color,
                stroke_width=stroke_width,
                duration=duration,
                # chars_per_sec=max(1, len(phrase) / duration)
                chars_per_sec = len(phrase) / (duration - buffer_time)
            ).with_start(start_t).with_end(end_t)

            # đặt vị trí như cũ
            if params.subtitle_position == "bottom":
                clip = clip.with_position(("center", video_height*0.95 - clip.h))
            elif params.subtitle_position == "top":
                clip = clip.with_position(("center", video_height*0.05))
            elif params.subtitle_position == "custom":
                margin, max_y = 10, video_height - clip.h - 10
                y = max(margin,
                        min((video_height - clip.h)*params.custom_position/100, max_y))
                clip = clip.with_position(("center", y))
            else:
                clip = clip.with_position(("center", "center"))

            return clip
        elif type_subtitle == "word2word":
            clip = (typewriter_word_clip(
                        text           = phrase,
                        font_path      = font_path,
                        font_size      = font_size,
                        color          = params.text_fore_color,
                        stroke_color   = params.stroke_color,
                        stroke_width   = stroke_width,
                        duration       = duration,
                        words_per_sec  = max(1, len(phrase.split())/duration),
                        video_w        = video_width,
                        video_h        = video_height,
                        subtitle_position = params.subtitle_position,
                        custom_pos     = params.custom_position,
                    )
                    .with_start(start_t)
                    .with_end(end_t))

            return clip

    video_clip = VideoFileClip(video_path).without_audio()
    audio_clip = AudioFileClip(audio_path).with_effects(
        [afx.MultiplyVolume(params.voice_volume)]
    )

    def make_textclip(text):
        return TextClip(
            text=text,
            font=font_path,
            font_size=params.font_size,
        )

    if subtitle_path and os.path.exists(subtitle_path):
        sub = SubtitlesClip(
            subtitles=subtitle_path, encoding="utf-8", make_textclip=make_textclip
        )
        text_clips = []
        for item in sub.subtitles:
            clip = create_text_clip(subtitle_item=item)
            text_clips.append(clip)
        video_clip = CompositeVideoClip([video_clip, *text_clips])

    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        try:
            bgm_clip = AudioFileClip(bgm_file).with_effects(
                [
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_clip.duration),
                ]
            )
            audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
        except Exception as e:
            logger.error(f"Thêm nhạc nền thất bại: {str(e)}")

    
    ffmpeg_extra = [
        "-crf", str(20),     
        "-movflags", "+faststart",     
    ]
    
    video_clip = video_clip.with_audio(audio_clip)
    video_clip.write_videofile(
        output_file,
        audio_codec=audio_codec,
        temp_audiofile_path=output_dir,
        threads=params.n_threads or 2,
        logger="bar",
        fps=fps,
        preset=preset,
        ffmpeg_params=ffmpeg_extra,
    )
    video_clip.close()
    del video_clip


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    for material_info in materials: # Đổi tên biến để tránh xung đột với module material
        if not material_info.url:
            continue

        ext = utils.parse_extension(material_info.url)
        clip = None # Khởi tạo clip để đảm bảo nó được định nghĩa
        try:
            clip = VideoFileClip(material_info.url)
        except Exception:
            try:
                clip = ImageClip(material_info.url)
            except Exception as e:
                logger.warning(f"Không thể đọc tài liệu {material_info.url}, bỏ qua: {str(e)}")
                continue

        width = clip.size[0]
        height = clip.size[1]
        if width < 480 or height < 480:
            logger.warning(f"Tài liệu độ phân giải thấp: {width}x{height} (tối thiểu 480x480 yêu cầu). Bỏ qua: {material_info.url}")
            close_clip(clip)
            continue

        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"Đang xử lý hình ảnh: {material_info.url}")
            # Tạo một clip hình ảnh và đặt thời lượng của nó
            clip_image_duration = clip_duration # Đặt thời lượng cho clip hình ảnh
            clip = (
                ImageClip(material_info.url)
                .set_duration(clip_image_duration)
                .set_position("center")
            )
            # Áp dụng hiệu ứng thu phóng
            zoom_clip = clip.resize(
                lambda t: 1 + (clip_image_duration * 0.03) * (t / clip_image_duration)
            )

            final_clip = CompositeVideoClip([zoom_clip])

            # Xuất video ra tệp
            video_file = f"{material_info.url}.mp4"
            # Đảm bảo thư mục đích tồn tại
            output_dir = os.path.dirname(video_file)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            final_clip.write_videofile(video_file, fps=30, logger=None, codec=video_codec, preset=preset)
            close_clip(clip) # Đóng clip gốc (ImageClip)
            close_clip(final_clip) # Đóng clip mới tạo
            material_info.url = video_file
            logger.success(f"Hình ảnh đã xử lý thành video: {video_file}")
        else: # Nếu là video, không làm gì ngoài việc kiểm tra và giữ lại đường dẫn gốc
            logger.info(f"Tài liệu video đã được xác minh: {material_info.url}")
            close_clip(clip) # Đóng clip sau khi kiểm tra
    return materials
