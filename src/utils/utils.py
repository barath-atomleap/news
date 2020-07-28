import logging

import cld3
from azure.storage.blob import BlobServiceClient
from delphai_backend_utils.config import get_config
from googletrans import Translator


def clean_url(url, keep_www=False):
  url = url.strip()
  url = url.replace('https://', '').replace('http://', '').rstrip('/')
  if not keep_www:
    url = url.replace('www.', '')
  split_url = url.split('/')
  split_url[0] = split_url[0].lower()
  return '/'.join(split_url)


def save_blob(url, text):
  try:
    blob_storage = get_config('blob_storage')
    # Create the BlobServiceClient object which will be used to create a container client
    blob_service_client = BlobServiceClient.from_connection_string(blob_storage['connection_string'])

    # Create a blob client using the local file name as the name for the blob
    blob_client = blob_service_client.get_blob_client(container=blob_storage['container'], blob=url)

    print("\nUploading to Azure Storage as blob:\n\t" + url)

    # Upload the created file
    blob_client.upload_blob(text)
  except Exception as e:
    logging.error('Exception:', e)
  return url


def is_text_in_english(text: str):
  """
    Detects the language of a given text and determines whether it is in English or not.
    :return: bool for whether text is in English or not
    """
  language = cld3.get_language(text)
  if str(language[0]) == "en":
    return True
  else:
    return False


def translate_to_english(text: str):
  """
    Translates given text to English.
    :param text: article text (str)
    :return: translated text (str)
    """
  translator = Translator()
  translated_text = translator.translate(text, dest="en")
  return translated_text.text
