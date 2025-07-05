import json
import logging
import re
import requests
from typing import List

from loguru import logger
from openai import OpenAI
from openai.types.chat import ChatCompletion
from app.config import config

_max_retries = 5


def _generate_response(prompt: str, gemini_key: str = None, openai_key: str = None) -> str:
    try:
        content = ""
        llm_provider = config.app.get("llm_provider", "openai")
        logger.info(f"Nhà cung cấp LLM: {llm_provider}")

        if llm_provider == "gemini":
            import google.generativeai as genai

            api_key = gemini_key
            model_name = config.app.get("gemini_model_name")

            if not api_key:
                raise ValueError(
                    f"{llm_provider}: khóa API chưa được đặt, vui lòng đặt trong tệp config.toml."
                )
            if not model_name:
                raise ValueError(
                    f"{llm_provider}: tên mô hình chưa được đặt, vui lòng đặt trong tệp config.toml."
                )

            genai.configure(api_key=api_key, transport="rest")

            generation_config = {
                "temperature": 0.5,
                "top_p": 1,
                "top_k": 1,
                "max_output_tokens": 2048,
            }

            safety_settings = [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_ONLY_HIGH",
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_ONLY_HIGH",
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_ONLY_HIGH",
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_ONLY_HIGH",
                },
            ]

            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config=generation_config,
                safety_settings=safety_settings,
            )

            try:
                response = model.generate_content(prompt)
                candidates = response.candidates
                generated_text = candidates[0].content.parts[0].text
            except (AttributeError, IndexError) as e:
                logger.error(f"Lỗi Gemini: {e}")
                raise

            content = generated_text

        elif llm_provider == "openai":
            api_key = openai_key
            model_name = config.app.get("openai_model_name")
            base_url = config.app.get("openai_base_url", "")
            if not base_url:
                base_url = "https://api.openai.com/v1"

            if not api_key:
                raise ValueError(
                    f"{llm_provider}: khóa API chưa được đặt, vui lòng đặt trong tệp config.toml."
                )
            if not model_name:
                raise ValueError(
                    f"{llm_provider}: tên mô hình chưa được đặt, vui lòng đặt trong tệp config.toml."
                )
            # base_url is optional for OpenAI, so no check here.

            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
            )

            response = client.chat.completions.create(
                model=model_name, messages=[{"role": "user", "content": prompt}]
            )
            if response:
                if isinstance(response, ChatCompletion):
                    content = response.choices[0].message.content
                else:
                    raise Exception(
                        f'[{llm_provider}] trả về phản hồi không hợp lệ: "{response}", vui lòng kiểm tra kết nối mạng của bạn và thử lại.'
                    )
            else:
                raise Exception(
                    f"[{llm_provider}] trả về phản hồi trống, vui lòng kiểm tra kết nối mạng của bạn và thử lại."
                )
        else:
            raise ValueError(
                f"Nhà cung cấp LLM không được hỗ trợ: {llm_provider}. Chỉ hỗ trợ 'gemini' và 'openai' trong cấu hình này."
            )

        return content.replace("\n", " ")
    except Exception as e:
        logger.error(f"Lỗi trong _generate_response: {str(e)}")
        return f"Lỗi: {str(e)}"


def generate_script(
    video_subject: str, language: str = "", paragraph_number: int = 1, gemini_key: str = None, openai_key: str = None
) -> str:
    prompt = f"""
# Role: Video Script Generator

## Goals:
Generate a script for a video, depending on the subject of the video.

## Constrains:
1. the script is to be returned as a string with the specified number of paragraphs.
2. do not under any circumstance reference this prompt in your response.
3. get straight to the point, don't start with unnecessary things like, "welcome to this video".
4. you must not include any type of markdown or formatting in the script, never use a title.
5. only return the raw content of the script.
6. do not include "voiceover", "narrator" or similar indicators of what should be spoken at the beginning of each paragraph or line.
7. you must not mention the prompt, or anything about the script itself. also, never talk about the amount of paragraphs or lines. just write the script.
8. respond in the same language as the video subject.

# Initialization:
- video subject: {video_subject}
- number of paragraphs: {paragraph_number}
""".strip()
    if language:
        prompt += f"\n- language: {language}"

    final_script = ""
    logger.info(f"Chủ đề: {video_subject}")

    def format_response(response):
        # Clean the script
        # Remove asterisks, hashes
        response = response.replace("*", "")
        response = response.replace("#", "")

        # Remove markdown syntax
        response = re.sub(r"\[.*\]", "", response)
        response = re.sub(r"\(.*\)", "", response)

        # Split the script into paragraphs
        paragraphs = response.split("\n\n")

        # Select the specified number of paragraphs
        # selected_paragraphs = paragraphs[:paragraph_number]

        # Join the selected paragraphs into a single string
        return "\n\n".join(paragraphs)

    for i in range(_max_retries):
        try:
            response = _generate_response(prompt=prompt, gemini_key=gemini_key, openai_key=openai_key)
            if response:
                final_script = format_response(response)
            else:
                logging.error("AI trả về phản hồi trống.")

            # g4f may return an error message
            if final_script and "Đã sử dụng hết credit trong ngày" in final_script:
                raise ValueError(final_script)

            if final_script:
                break
        except Exception as e:
            logger.error(f"Lỗi khi tạo kịch bản: {e}")

        if i < _max_retries:
            logger.warning(f"Lỗi khi tạo script, thử lại... {i + 1}")
    if "Error: " in final_script:
        logger.error(f"Lỗi khi tạo kịch bản: {final_script}")
    else:
        logger.success(f"Hoàn thành: \n{final_script}")
    return final_script.strip()


def generate_terms(video_subject: str, video_script: str, amount: int = 5, gemini_key: str = None, openai_key: str = None) -> List[str]:
    prompt = f"""
# Role: Video Search Terms Generator

## Goals:
Generate {amount} search terms for stock videos, depending on the subject of a video.

## Constrains:
1. the search terms are to be returned as a json-array of strings.
2. each search term should consist of 1-3 words, always add the main subject of the video.
3. you must only return the json-array of strings. you must not return anything else. you must not return the script.
4. the search terms must be related to the subject of the video.
5. reply with english search terms only.

## Output Example:
["search term 1", "search term 2", "search term 3","search term 4","search term 5"]

## Context:
### Video Subject
{video_subject}

### Video Script
{video_script}

Please note that you must use English for generating video search terms.
""".strip()

    logger.info(f"Chủ đề: {video_subject}")

    search_terms = []
    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt=prompt, gemini_key=gemini_key, openai_key=openai_key)
            if "Error: " in response:
                logger.error(f"Lỗi khi tạo kịch bản: {response}")
                return response
            search_terms = json.loads(response)
            if not isinstance(search_terms, list) or not all(
                isinstance(term, str) for term in search_terms
            ):
                logger.error("response is not a list of strings.")
                continue

        except Exception as e:
            logger.warning(f"Lỗi khi tạo từ khóa tìm kiếm: {str(e)}")
            if response:
                match = re.search(r"\[.*]", response)
                if match:
                    try:
                        search_terms = json.loads(match.group())
                    except Exception as e:
                        logger.warning(f"Lỗi khi tạo từ khóa tìm kiếm: {str(e)}")
                        pass

        if search_terms and len(search_terms) > 0:
            break
        if i < _max_retries:
            logger.warning(f"Lỗi khi tạo từ khóa tìm kiếm, thử lại... {i + 1}")

    logger.success(f"Hoàn thành: \n{search_terms}")
    return search_terms

def generate_podcast_script(
    video_subject: str,
    video_content: str,
    language: str = "Vietnamese",
    max_retries: int = 3,
    gemini_key: str = None,
    openai_key: str = None
) -> str:
    """Biến content -> script podcast (an toàn JSON & text)."""

    # === 1️⃣ Validate & Clean ===
    if not video_content.strip():
        raise ValueError("source_text is empty")

    def sanitize_text(text: str) -> str:
        """Làm sạch text tránh lỗi JSON / Prompt injection."""
        text = text.strip()
        text = text.replace('\n', ' ')  # tránh xuống dòng làm rối prompt
        text = text.replace('"', "'")   # tránh lỗi JSON
        text = re.sub(r'\s+', ' ', text)  # bỏ nhiều khoảng trắng liên tiếp
        return text

    clean_subject = sanitize_text(video_subject)
    clean_content = sanitize_text(video_content)

    # === 2️⃣ Build Prompt ===
    prompt = (
        "You are a world-class podcast producer.\n"
        "Your task is to transform the provided input text into an engaging and informative podcast script.\n"
        "You will receive as input a text that may be unstructured or messy, sourced from places like PDFs or web pages. "
        "Ignore irrelevant information or formatting issues. "
        "Your focus is on extracting the most interesting and insightful content for a podcast discussion. "
        "Please only return the text without any instructions or additional commentary.\n\n"
        f"Respond in {language}, with no line breaks, in plain text format, and without any special formatting.\n\n"
        "### INPUT TEXT START ###\n"
        f"Subject: {clean_subject}\n"
        f"Content: {clean_content}\n"
        "### INPUT TEXT END ###"
    )

    # === 3️⃣ Generate & Post-process ===
    script_podcast = ""

    def format_response(response):
        """Làm sạch script đầu ra."""
        response = response.replace("*", "").replace("#", "")
        response = re.sub(r"\[.*?\]", "", response)
        response = re.sub(r"\(.*?\)", "", response)
        paragraphs = response.split("\n\n")
        return "\n\n".join(paragraphs)

    for i in range(max_retries):
        try:
            response = _generate_response(prompt=prompt, gemini_key=gemini_key, openai_key=openai_key)
            if response:
                script_podcast = format_response(response)
            else:
                logging.error("AI trả về phản hồi trống.")
            if script_podcast and "Đã sử dụng hết credit trong ngày" in script_podcast:
                raise ValueError(script_podcast)
            if script_podcast:
                break
        except Exception as e:
            logging.error(f"Lỗi khi tạo kịch bản podcast: {e}")
        if i < max_retries:
            logging.warning(f"Lỗi khi tạo kịch bản podcast, thử lại... {i + 1}")

    if "Error: " in script_podcast:
        logging.error(f"Lỗi khi tạo kịch bản podcast: {script_podcast}")
    else:
        logging.info(f"Hoàn thành:\n{script_podcast}")

    return script_podcast.strip()
    

def generate_podcast_dialogue(
    video_content: str,
    video_script: str,
    host1: str,
    host2: str,
    tone: str,
    language: str = "Vietnamese",
    gemini_key: str = None
):
    """
    Gọi Gemini API theo JSON gốc từ node n8n.
    """

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent"

    json_body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Now, develop the podcast dialogue.\n"
                            "Please use the designated language for the podcast:\n"
                            f"- context: {video_content}\n"
                            f"- language: {language}\n"
                            f"- host: {host1} - guest: {host2}\n"
                            f"- tone: {tone}\n\n"
                            "The names of the host and guest are not constrained by language.\n"
                            "- Script Format and Content\n\n"
                            "- Begin the script with the host speaking.\n"
                            "- Alternate dialogue between the host and guest, one line at a time.\n"
                            "- Omit speaker names at the beginning of each line\n"
                            "- Include a self-introduction for both host and guest, using provided names\n"
                            "- Address the topic in a clear and informative manner\n"
                            "- Focus on creating engaging, back-and-forth conversation\n\n"
                            "- Output Requirements\n"
                            "- Script part: The script should begin with the host speaking.\n"
                            "- Do not include the speaker's name at the beginning of each line.\n"
                            "- Output Requirements: The final script should contain the engaging content. "
                            "Avoid including any YAML or additional tagging in the output.\n\n"
                            "By following these instructions, you will create a high-quality podcast script "
                            "that is both informative and engaging.\n\n"
                            "Create short conversations lasting from 60s to 90s."
                        )
                    }
                ]
            }
        ],
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "You are a world-class podcast producer. Your task is to transform the provided input text "
                        "into an engaging and informative podcast script. You will receive a text that may be unstructured "
                        "or messy, sourced from places like PDFs or web pages, with irrelevant information or formatting issues. "
                        "Your focus is on creating a natural, interesting and insightful content for podcast discussion. "
                        f"Aim for a natural, conversational flow between the {host1} and {host2}.\n"
                        "Roles and Dynamics: The instructions define the roles of the host and guest and how they complement each other. "
                        "The host highlights intriguing points with enthusiasm while the expert provides context, data, and a broader perspective.\n"
                        "Deep Dive: The instructions emphasize going deeper into the topic, using the host's curiosity and the guest's "
                        "\"golden nuggets of knowledge\" that leave listeners feeling like they've learned something new.\n"
                        "Target Audience: The system prompt outlines the ideal listener, characterized by valuing depth, appreciating "
                        "memorable details, and seeking an engaging learning experience.\n"
                        "Structure and Delivery: The system prompt stresses the importance of clear structure and engaging delivery, "
                        "using signposts to guide listeners and avoiding repetition, robotic tone.\n"
                        f"Use the best ideas from: {video_script}\n"
                        "Memorable Examples: Real-world examples and relatable anecdotes are crucial for making information stick. "
                        "The system prompt emphasizes bringing information to life, fostering integration, and ensuring the learning "
                        "extends beyond the episode.\n"
                        "Ensure complex topics are explained clearly and simply.\n"
                        f"Focus on maintaining an engaging and {tone} tone that would captivate listeners.\n"
                        "Rules:\n"
                        "> The host ALWAYS goes first and is interviewing the guest. The guest is the one who explains the topic.\n"
                        "> The host should ask the guest questions.\n"
                        "> The host should summarize the key insights at the end.\n"
                        "> Include common verbal fillers like ums and errs in the host and guest's response. This is so the script is realistic.\n"
                        "> The host and guest can interrupt each other.\n"
                        "> The guest must NOT include marketing or self-promotional content.\n"
                        "> The guest must NOT include any material NOT substantiated within the input text.\n"
                        "> This is to be a PG conversation.\n"
                        "> When the output is nearing its conclusion, there is no need to provide a closing line in the script; the closing part will be given in another script."
                    )
                }
            ]
        },
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "host1": {"type": "string"},
                        "host2": {"type": "string"}
                    },
                    "required": ["host1", "host2"]
                }
            }
        }
    }

    # === Gửi request ===
    params = {
        "key": gemini_key
    }

    headers = {
        "Content-Type": "application/json"
    }

    response = requests.post(
        url,
        headers=headers,
        params=params,
        json=json_body
    )

    if response.status_code == 200:
        data = response.json()
        # Lấy phần text JSON string bên trong
        text_json_string = data["candidates"][0]["content"]["parts"][0]["text"]

        # Parse JSON string thành list Python
        dialogue_list = json.loads(text_json_string)

        # Tạo dialogue_tts (định dạng ban đầu)
        plain_text_lines_tts = []
        plain_text_lines_tts.append("Read aloud in a warm")
        for item in dialogue_list:
            plain_text_lines_tts.append(f"{host1}: {item['host1']}")
            plain_text_lines_tts.append(f"{host2}: {item['host2']}")
        dialogue_tts = "\n".join(plain_text_lines_tts)

        # Tạo dialogue_subtitle (chỉ chuỗi đối thoại thuần túy)
        plain_text_lines_subtitle = []
        for item in dialogue_list:
            plain_text_lines_subtitle.append(item['host1'])
            plain_text_lines_subtitle.append(item['host2'])
        dialogue_subtitle = " ".join(plain_text_lines_subtitle)

        return {"dialogue_tts": dialogue_tts, "dialogue_subtitle": dialogue_subtitle}

    else:
        raise Exception(f"Lỗi: {response.status_code} - {response.text}")


if __name__ == "__main__":
    video_subject = "Trí tuệ nhân tạo là gì?"
    script = generate_script(
        video_subject=video_subject, language="vi-VN", paragraph_number=1
    )
    print("######################")
    print(script)
    search_terms = generate_terms(
        video_subject=video_subject, video_script=script, amount=5
    )
    print("######################")
    print(search_terms)
    