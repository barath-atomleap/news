from delphai_utils.logging import logging
import cld3
from proto.proto.translation_pb2_grpc import TranslationStub
from proto.proto.translation_pb2 import TranslateRequest, TranslateResponse
from proto.proto.translation_pb2 import DetectLanguageRequest, DetectLanguageResponse
from azure.storage.blob.aio import BlobServiceClient
from azure.core.exceptions import ResourceExistsError
from delphai_utils.config import get_config
from googletrans import Translator
from delphai_utils.grpc_client import get_grpc_client
import grpc

translation_client = get_grpc_client(TranslationStub, get_config('translation.address'))


async def save_blob(key, content):
  try:
    storage_connection_string = get_config('blob_storage.connection_string')
    storage_container_name = get_config('blob_storage.container')
    storage_client = BlobServiceClient.from_connection_string(storage_connection_string, logging_enable=False)
    news_container_client = storage_client.get_container_client(storage_container_name)
    async with news_container_client:
      blob_client = news_container_client.get_blob_client(key)
      await blob_client.upload_blob(content, overwrite=True)
    logging.info(f'[wrote to blob] {key}')
  except ResourceExistsError as er:
    logging.warning(f'Existing blob: {er}')
  except Exception as e:
    logging.error('Error saving blob:', e)
    return ''
  return key


async def is_text_in_english(text: str):
  """
    Detects the language of a given text and determines whether it is in English or not.
    :return: bool for whether text is in English or not
    """

  try:
    req = DetectLanguageRequest(text=text)
    detected_lang: DetectLanguageResponse = await translation_client.detect_language(req)
    if detected_lang.language == "en":
      return True
    else:
      return False
  except Exception as e:
    logging.warning(f'lang detect failed: {e}')
    language = cld3.get_language(text)
    if str(language[0]) == "en":
      return True
    else:
      return False


async def check_language(text: str):
  """
    Detects the language of a given text and returns the language.
    :return: language code
    """

  try:
    req = DetectLanguageRequest(text=text)
    detected_lang: DetectLanguageResponse = await translation_client.detect_language(req)
    return detected_lang.language
  except grpc.aio._call.AioRpcError as rpc_ex:
    message_code = rpc_ex.code()
    message_details = rpc_ex.details()
    full_message = f'gRPC error: {message_code} {message_details}'
    if message_code == grpc.StatusCode.UNAVAILABLE:
      logging.error(
        f'The ongoing request is terminated as the server is not available or closed already.\nMessage: {full_message}')
      raise rpc_ex
    elif message_code == grpc.StatusCode.INTERNAL:
      logging.error(f'Internal error on the server side.\nMessage: {full_message}')
      raise rpc_ex
    elif message_code == grpc.StatusCode.UNKNOWN:
      logging.error(full_message)
    else:
      logging.error(full_message)


async def translate_to_english(non_eng_text: str):
  """
    Translates given text to English.
    :param non_eng_text: article text (str)
    :return: translated text (str)
    """

  try:
    req = TranslateRequest(text=non_eng_text, method='azure')
    translated_text: TranslateResponse = await translation_client.translate(req)

    return translated_text.translation
  except Exception as e:
    logging.warning(f'translation service failed: {e}')
    retry_count = 15
    english_text = None
    for i in range(0, retry_count, 1):
      try:
        translator = Translator()
        translated_text = translator.translate(non_eng_text, dest="en")
        english_text = translated_text.text
        return english_text
      except AttributeError as e:
        logging.error(f'Error translating with google trans: {e}. Text = {non_eng_text[:100]}. Retry {i}')
    return english_text
