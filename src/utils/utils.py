from delphai_utils.logging import logging
import cld3
from proto.proto.translation_pb2_grpc import TranslationStub
from proto.proto.translation_pb2 import TranslateRequest, TranslateResponse
from proto.proto.translation_pb2 import DetectLanguageRequest, DetectLanguageResponse
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError
from delphai_utils.config import get_config
from googletrans import Translator
from delphai_utils.grpc_client import get_grpc_client

translation_client = get_grpc_client(TranslationStub, get_config('translation.address'))


async def save_blob(url, text):
  try:
    blob_storage = get_config('blob_storage')
    # Create the BlobServiceClient object which will be used to create a container client
    blob_service_client = BlobServiceClient.from_connection_string(blob_storage['connection_string'])

    # Create a blob client using the local file name as the name for the blob
    blob_client = blob_service_client.get_blob_client(container=blob_storage['container'], blob=url)

    logging.info("Uploading to Azure Storage as blob:\t" + url)

    # Upload the created file
    await blob_client.upload_blob(text)
  except ResourceExistsError:
    # logging.warning(f'Existing blob: {e}')
    pass
  except Exception as e:
    logging.error('Exception:', e)
  return url


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
  except Exception as e:
    logging.warning(f'lang detect failed: {e}')
    language = cld3.get_language(text)
    return str(language[0])


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
