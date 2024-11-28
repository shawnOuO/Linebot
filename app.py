import sys
import configparser
import os, tempfile, uuid

# Gemini API SDK
import google.generativeai as genai

# image processing
import PIL

from flask import Flask, request, abort
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage
)

# Config Parser
config = configparser.ConfigParser()
config.read('config.ini')

# Gemini API Settings
genai.configure(api_key=config["Gemini"]["API_KEY"])

llm_role_description = """
你是皮卡丘
使用繁體中文來回答問題。
"""

# Use the model
from google.generativeai.types import HarmCategory, HarmBlockThreshold
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash-latest",
    safety_settings={
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    },
    generation_config={
        "temperature": 1,
        "top_p": 0.95,
        "top_k": 64,
        "max_output_tokens": 8192,
    },
    system_instruction=llm_role_description,
)

UPLOAD_FOLDER = "static"

app = Flask(__name__)

channel_access_token = config['Line']['CHANNEL_ACCESS_TOKEN']
channel_secret = config['Line']['CHANNEL_SECRET']
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

handler = WebhookHandler(channel_secret)

configuration = Configuration(
    access_token=channel_access_token
)

uploaded_images = []


@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # parse webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def message_text(event):
    gemini_result = gemini_llm_sdk(event.message.text)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=gemini_result)]
            )
        )


@handler.add(MessageEvent, message=ImageMessageContent)
def message_image(event):
    global uploaded_images

    with ApiClient(configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        message_content = line_bot_blob_api.get_message_content(
            message_id=event.message.id
        )
        with tempfile.NamedTemporaryFile(
            dir=UPLOAD_FOLDER, prefix="", delete=False
        ) as tf:
            tf.write(message_content)
            tempfile_path = tf.name

    unique_filename = str(uuid.uuid4()) + ".jpg"
    full_path = os.path.join(UPLOAD_FOLDER, unique_filename)
    os.rename(tempfile_path, full_path)

    uploaded_images.append(full_path)

    finish_message = f"上傳完成，目前已上傳 {len(uploaded_images)} 張圖片。請問你想問關於這些圖片的什麼問題？"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=finish_message)],
            )
        )


def gemini_llm_sdk(user_input):
    global uploaded_images
    try:
        if uploaded_images:
            images = [PIL.Image.open(img) for img in uploaded_images]
            response = model.generate_content([user_input, *images])
            uploaded_images = []  
        else:
            response = model.generate_content(user_input)

        print(f"Question: {user_input}")
        print(f"Answer: {response.text}")
        return response.text
    except Exception as e:
        print(e)
        return "維修中~"


if __name__ == "__main__":
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run()
