import re
import os
import time
import requests
import subprocess
from typing import List, Optional, Dict, Any
from pathlib import Path

from loguru import logger

from app.config import config


def _generate_image_flux(prompt: str, segment: int, base_path: str, width: int = 1080, height: int = 1920, steps: int = 3, max_retries: int = 3, retry_delay: int = 2) -> Optional[str]:
    """
    Tạo ảnh sử dụng API Flux Pro Unlimited trên Hugging Face Space.
    
    Args:
        prompt: Prompt văn bản để tạo ảnh
        segment: Số segment cho tên file ảnh
        base_path: Đường dẫn cơ sở để lưu ảnh
        width: Chiều rộng ảnh (mặc định: 1080)
        height: Chiều cao ảnh (mặc định: 1920)
        steps: Số bước tạo ảnh (mặc định: 3)
        max_retries: Số lần thử lại tối đa cho các cuộc gọi API (mặc định: 3)
        retry_delay: Độ trễ giữa các lần thử lại (giây) (mặc định: 2)
        
    Returns:
        Đường dẫn đến ảnh PNG đã tạo hoặc None nếu tạo thất bại
    """
    # Đảm bảo thư mục đích tồn tại
    base_path = Path(base_path)
    base_path.mkdir(parents=True, exist_ok=True)
    
    # Tạo tên file dựa trên segment
    output_jpg = base_path / f"segment_{segment}.jpg"
    output_png = base_path / f"segment_{segment}.png"
    
    # API endpoint và headers
    api_url = "https://nihalgazi-flux-pro-unlimited.hf.space/gradio_api/call/generate_image"
    headers = {
        "Authorization": "Bearer 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",
        "Content-Type": "application/json"
    }
    
    # Dữ liệu request
    data = {
        "data": [
            prompt,
            width,
            height,
            steps,
            True,
            "Google US Server"
        ]
    }
    
    logger.info(f"Đang tạo ảnh với prompt: {prompt[:50]}...")
    
    # Thực hiện request với cơ chế thử lại
    for attempt in range(max_retries):
        try:
            # Gửi request ban đầu để khởi tạo quá trình tạo ảnh
            response = requests.post(api_url, headers=headers, json=data, timeout=60)
            response.raise_for_status()
            
            # Lấy event_id từ phản hồi
            event_id = response.json().get("event_id")
            if not event_id:
                logger.error("Không tìm thấy event_id trong phản hồi")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
            
            logger.info(f"Đã nhận event_id: {event_id}, đang chờ kết quả...")
            
            # Gửi request để lấy kết quả
            result_url = f"https://nihalgazi-flux-pro-unlimited.hf.space/gradio_api/call/generate_image/{event_id}"
            
            # Thử lấy kết quả với timeout
            max_result_attempts = 30  # Tối đa 30 lần thử (5 phút với 10 giây mỗi lần)
            image_url = None
            
            for result_attempt in range(max_result_attempts):
                try:
                    result_response = requests.get(result_url, headers=headers, timeout=30)
                    result_response.raise_for_status()
                    
                    # Phân tích phản hồi để tìm URL ảnh
                    raw_data = result_response.text
                    lines = raw_data.split("\n")
                    
                    # Tìm dòng có `event: complete`
                    complete_line_index = next((i for i, line in enumerate(lines) if line.startswith("event: complete")), -1)
                    
                    if complete_line_index != -1 and complete_line_index + 1 < len(lines) and lines[complete_line_index + 1].startswith("data: "):
                        json_string = lines[complete_line_index + 1].replace("data: ", "").strip()
                        parsed_data = json.loads(json_string)
                        
                        # Tìm đối tượng chứa URL
                        file_obj = next((item for item in parsed_data if isinstance(item, dict) and "url" in item), None)
                        
                        if file_obj and "url" in file_obj:
                            image_url = file_obj["url"]
                            logger.info(f"Đã tìm thấy URL ảnh: {image_url}")
                            break
                    
                    # Nếu chưa hoàn thành, đợi và thử lại
                    time.sleep(10)
                    
                except Exception as e:
                    logger.warning(f"Lỗi khi lấy kết quả (lần thử {result_attempt+1}/{max_result_attempts}): {str(e)}")
                    time.sleep(retry_delay)
            
            # Nếu không tìm thấy URL ảnh sau nhiều lần thử
            if not image_url:
                logger.error("Không thể lấy URL ảnh sau nhiều lần thử")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
            
            # Tải ảnh từ URL
            logger.info(f"Đang tải ảnh từ URL: {image_url}")
            img_response = requests.get(image_url, headers=headers, timeout=30)
            img_response.raise_for_status()
            
            # Lưu ảnh vào file
            with open(output_jpg, "wb") as f:
                f.write(img_response.content)
            
            logger.info(f"Đã lưu ảnh JPG: {output_jpg}")
            
            # Chuyển đổi JPG sang PNG sử dụng ffmpeg
            try:
                cmd = [
                    "ffmpeg",
                    "-y",  # Ghi đè file nếu đã tồn tại
                    "-i", str(output_jpg),  # File đầu vào
                    str(output_png)  # File đầu ra
                ]
                
                logger.info(f"Đang chuyển đổi JPG sang PNG: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                
                # Xóa file JPG sau khi chuyển đổi thành công
                if output_png.exists():
                    output_jpg.unlink()
                    logger.info(f"Đã chuyển đổi thành công và xóa file JPG")
                    return str(output_png)
                else:
                    logger.error(f"Chuyển đổi thất bại: File PNG không tồn tại")
                    return str(output_jpg)  # Trả về file JPG nếu chuyển đổi thất bại
                    
            except subprocess.CalledProcessError as e:
                logger.error(f"Lỗi khi chuyển đổi JPG sang PNG: {e.stderr}")
                return str(output_jpg)  # Trả về file JPG nếu chuyển đổi thất bại
                
        except requests.RequestException as e:
            logger.error(f"Lỗi request (lần thử {attempt+1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Đang thử lại sau {retry_delay} giây...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Đã thử {max_retries} lần nhưng vẫn thất bại")
                return None
    
    return None

def _generate_image_together(prompt: str, segment: int, base_path: str, width: int = 1080, height: int = 1920, steps: int = 3, max_retries: int = 3, retry_delay: int = 2) -> Optional[str]:
    """
    Generates an image using the Together.xyz API based on the provided prompt.
    
    Args:
        prompt: The text prompt to generate the image from
        segment: The segment number for the image filename
        base_path: The base path to save the image
        width: Image width (default: 1008)
        height: Image height (default: 1792)
        steps: Number of steps for image generation (default: 4)
        n: Number of images to generate (default: 4)
        max_retries: Maximum number of retry attempts for API calls (default: 3)
        retry_delay: Delay in seconds between retry attempts (default: 2)
        
    Returns:
        The path to the generated PNG image or None if generation failed
    """
    # Ensure base_path exists
    base_path = Path(base_path)
    base_path.mkdir(parents=True, exist_ok=True)
    
    # Prepare file paths
    jpg_path = base_path / f"image_{segment}.jpg"
    png_path = base_path / f"image_{segment}.png"
    
    # API configuration
    api_url = "https://api.together.xyz/v1/images/generations"
    headers = {
        "Authorization": "Bearer e529576857fb0e066ad94f17bf4cf1053ffb4d3dd9f81e15368560ae21f0efd9",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "black-forest-labs/FLUX.1-schnell-Free",
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "n": n
    }
    
    # Implement retry logic for API calls
    for attempt in range(max_retries):
        try:
            # Step 1: Make the initial API request to generate the image
            logger.info(f"Gửi yêu cầu tạo ảnh (lần thử {attempt+1}/{max_retries})")
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data.get('data') or len(data['data']) == 0 or not data['data'][0].get('url'):
                logger.error(f"Không nhận được URL hình ảnh từ API: {data}")
                if attempt < max_retries - 1:
                    logger.info(f"Thử lại sau {retry_delay} giây...")
                    time.sleep(retry_delay)
                    continue
                return None
            
            # Step 2: Download the generated image
            image_url = data['data'][0]['url']
            logger.info(f"Tải xuống hình ảnh từ URL: {image_url}")
            image_response = requests.get(image_url, timeout=30)
            image_response.raise_for_status()
            
            # Step 3: Save the image as JPG
            with open(jpg_path, 'wb') as f:
                f.write(image_response.content)
            logger.info(f"Đã lưu hình ảnh JPG: {jpg_path}")
            
            # Step 4: Convert JPG to PNG using ffmpeg
            ffmpeg_path = config.app.get("ffmpeg_path", "ffmpeg")
            
            cmd = [ffmpeg_path, "-y", "-i", str(jpg_path), str(png_path)]
            logger.info(f"Chuyển đổi JPG sang PNG: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            
            if png_path.exists():
                logger.info(f"Đã tạo và lưu hình ảnh thành công: {png_path}")
                return str(png_path)
            else:
                logger.error(f"Không thể tạo file PNG. Kết quả ffmpeg: {result.stdout}\n{result.stderr}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Lỗi kết nối API (lần thử {attempt+1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Thử lại sau {retry_delay} giây...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Đã hết số lần thử. Không thể tạo hình ảnh.")
                return None
        except subprocess.CalledProcessError as e:
            logger.error(f"Lỗi khi chạy ffmpeg: {str(e)}\nOutput: {e.stdout}\nError: {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"Lỗi không xác định khi tạo hình ảnh: {str(e)}")
            return None
    
    return None


if __name__ == "__main__":
    # Ví dụ sử dụng các hàm tạo ảnh
    pass